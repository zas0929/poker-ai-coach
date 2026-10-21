'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import ActionPanel from '@/components/ActionPanel';
import HandHistory from '@/components/HandHistory';
import PokerTable from '@/components/PokerTable';
import { enterRoom, roomSocketUrl } from '@/services/roomApi';
import type { RoomCredentials, RoomState } from '@/services/roomApi';
import type { ActionType } from '@/types/poker';

export default function FriendsPage() {
  const [credentials, setCredentials] = useState<RoomCredentials | null>(null);
  const [room, setRoom] = useState<RoomState | null>(null);
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [status, setStatus] = useState('Choose a room');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const socket = useRef<WebSocket | null>(null);
  const latest = useRef<RoomState | null>(null);
  const pending = useRef<{ id: string; payload: string } | null>(null);
  const commandTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const entering = useRef(false);

  useEffect(() => {
    const invitation = new URLSearchParams(window.location.search).get('room')?.trim().toUpperCase();
    if (invitation) {
      // URL and local storage are available only after browser hydration.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCode(invitation);
      try {
        const saved = sessionStorage.getItem(`poker-room:${invitation}`) ?? localStorage.getItem(`poker-room:${invitation}`);
        if (saved) setCredentials(JSON.parse(saved));
      } catch { /* Browser storage may be disabled. */ }
    }
  }, []);

  useEffect(() => {
    if (!credentials) return;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    const connect = () => {
      if (stopped) return;
      setStatus('Connecting');
      const ws = new WebSocket(roomSocketUrl(credentials.code));
      socket.current = ws;
      let firstSnapshot = true;
      ws.onopen = () => ws.send(JSON.stringify({ token: credentials.token }));
      ws.onmessage = (event) => {
        if (stopped) return;
        const message = JSON.parse(event.data);
        if (message.type === 'state') {
          latest.current = message;
          setRoom(message);
          setStatus('Connected');
          attempt = 0;
          // Only retry the exact command; the server deduplicates its ID.
          if (firstSnapshot && pending.current) ws.send(pending.current.payload);
          firstSnapshot = false;
        } else if (message.type === 'error') {
          pending.current = null;
          setBusy(false);
          setError(message.message);
        } else if (message.type === 'ack' && pending.current?.id === message.command_id) {
          pending.current = null;
          setBusy(false);
          if (commandTimer.current) clearTimeout(commandTimer.current);
        }
      };
      ws.onclose = (event) => {
        if (stopped) return;
        if (event.code === 1008) {
          pending.current = null;
          setBusy(false);
          setStatus('Seat unavailable');
          setError('This seat or room is no longer available. Rooms are cleared on server restart.');
          return;
        }
        setStatus('Reconnecting');
        retry = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10000));
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      if (commandTimer.current) clearTimeout(commandTimer.current);
      socket.current?.close();
      socket.current = null;
    };
  }, [credentials]);

  const enter = async (join: boolean) => {
    if (entering.current) return;
    entering.current = true;
    setBusy(true);
    setError(null);
    try {
      const next = await enterRoom(name.trim(), join ? code.trim().toUpperCase() : undefined);
      try { sessionStorage.setItem(`poker-room:${next.code}`, JSON.stringify(next)); } catch { /* Keep this session. */ }
      try { localStorage.setItem(`poker-room:${next.code}`, JSON.stringify(next)); } catch { /* Keep this session. */ }
      window.history.replaceState(null, '', `/friends?room=${next.code}`);
      setCode(next.code);
      setCredentials(next);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not enter room.'); }
    finally { setBusy(false); entering.current = false; }
  };

  const send = (kind: string, values: Record<string, unknown> = {}) => {
    if (pending.current || socket.current?.readyState !== WebSocket.OPEN || !latest.current) return;
    const id = crypto.randomUUID();
    const payload = JSON.stringify({ command_id: id, revision: latest.current.revision, kind, ...values });
    pending.current = { id, payload };
    setBusy(true);
    setError(null);
    socket.current.send(payload);
    commandTimer.current = setTimeout(() => {
      // Reconnect rather than generate a new ID for an uncertain action.
      if (pending.current?.id === id) socket.current?.close();
    }, 7000);
  };
  const action = (chosen: ActionType, amount?: number) => send('action', { action: chosen, amount, hand_id: room?.hand?.hand_id });
  const me = room?.members.find((member) => member.player_id === room.viewer_id);
  const hand = room?.hand ?? null;
  const betweenHands = !hand || Boolean(hand.result);
  const connected = status === 'Connected';
  const isHost = room?.viewer_id === room?.host_id;
  const everyoneReady = Boolean(room && room.members.length >= 2 && room.members.every((member) => member.ready && member.connected));

  const copyInvite = async () => {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/friends?room=${credentials?.code}`);
      setCopied(true);
    } catch { setError('Copy the invitation link from the field below.'); }
  };
  const reset = () => {
    setCredentials(null); setRoom(null); latest.current = null; pending.current = null;
    setBusy(false); setError(null); setStatus('Choose a room'); setCode('');
    window.history.replaceState(null, '', '/friends');
  };

  return (
    <main className="app-shell">
      <section className="top-bar">
        <div><p className="eyebrow">Private tables · virtual chips</p><h1>Play with friends</h1></div>
        <div className="status-row"><span className="status-pill">{status}</span><Link className="mode-link" href="/">AI training</Link></div>
      </section>
      {error ? <div className="error-banner"><span>{error}</span><button onClick={() => setError(null)}>Dismiss</button></div> : null}
      {!credentials ? (
        <section className="room-entry control-panel">
          <h2>Your private poker table</h2>
          <p>Create a room and share its invitation. Bring 2–6 players, mark everyone ready, then deal.</p>
          <label>Your name<input autoComplete="nickname" maxLength={24} value={name} onChange={(event) => setName(event.target.value)} placeholder="Roman" /></label>
          <button className="primary-button" disabled={busy || !name.trim()} onClick={() => enter(false)}>Create room</button>
          <div className="room-join"><label>Room code<input maxLength={8} value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} placeholder="Invitation code" /></label><button disabled={busy || !name.trim() || code.trim().length !== 8} onClick={() => enter(true)}>Join room</button></div>
          <p className="room-note">Local preview. Friends on other networks will need the hosting stage. Rooms and seats currently live in server memory.</p>
        </section>
      ) : (
        <>
          <section className="room-toolbar control-panel">
            <div><span className="eyebrow">Room {credentials.code}</span><strong>{me?.name ?? 'Restoring your seat'} · {room?.members.length ?? 1}/6 players</strong></div>
            <button onClick={copyInvite}>{copied ? 'Link copied' : 'Copy invitation'}</button>
            <button onClick={reset}>Other room</button>
            <input className="invite-field" aria-label="Invitation link" readOnly value={typeof window === 'undefined' ? '' : `${window.location.origin}/friends?room=${credentials.code}`} />
          </section>
          <section className="game-layout">
            <div className="table-column">
              <PokerTable hand={hand} seatCount={hand?.players.length ?? Math.max(2, room?.members.length ?? 2)} viewerId={room?.viewer_id} />
              {hand ? <ActionPanel analysis={null} hand={hand} isLoading={busy || !connected} viewerId={room?.viewer_id} trainingControls={false} onAction={action} onAdvance={() => {}} onAnalyze={() => {}} onStartHand={() => {}} /> : null}
            </div>
            <aside className="side-column">
              <section className="control-panel room-lobby">
                <h2>{betweenHands ? 'Ready for the next hand?' : 'Players at the table'}</h2>
                <ul>{room?.members.map((member) => <li key={member.player_id}><div><strong>{member.name}{member.player_id === room.viewer_id ? ' (you)' : ''}</strong><span>{member.player_id === room.host_id ? 'Host · ' : ''}{member.connected ? 'Connected' : 'Disconnected'}</span></div><em>{member.ready ? 'Ready' : betweenHands ? 'Waiting' : 'Playing'}</em></li>)}</ul>
                {betweenHands ? <><button disabled={busy || !connected} onClick={() => send('ready', { ready: !me?.ready })}>{me?.ready ? 'Not ready' : "I'm ready"}</button>{isHost ? <button className="primary-button" disabled={busy || !connected || !everyoneReady} onClick={() => send('start')}>{hand ? 'Deal next hand' : 'Deal first hand'}</button> : <p>The host deals when everyone is ready.</p>}</> : <p>{hand?.players.find((player) => player.id === hand.current_player_id)?.name}&apos;s turn. Streets advance automatically.</p>}
                <p className="room-note">Blinds 5/10 · Starting stack 1000. Virtual training chips: stacks below 10 receive 1000 extra chips between hands. Invite everyone before the first deal. Reopen this link in the same browser to restore your seat.</p>
                <p className="room-note">Disconnected players keep their seat; the table waits for them to reconnect. Timers and sit-out are planned next.</p>
              </section>
              <HandHistory hand={hand} />
            </aside>
          </section>
        </>
      )}
    </main>
  );
}
