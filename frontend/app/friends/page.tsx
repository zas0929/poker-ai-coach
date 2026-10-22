'use client';

import { useI18n } from '@/i18n/LanguageProvider';

import Link from 'next/link';
import AppHeader from '@/components/AppHeader';
import { useEffect, useRef, useState } from 'react';
import ActionPanel from '@/components/ActionPanel';
import HandHistory from '@/components/HandHistory';
import HandArchive from '@/components/HandArchive';
import PokerTable from '@/components/PokerTable';
import PanelSidebar from '@/components/PanelSidebar';
import { enterRoom, roomSocketUrl } from '@/services/roomApi';
import type { RoomCredentials, RoomState, RoomSettings } from '@/services/roomApi';
import type { ActionType } from '@/types/poker';

export default function FriendsPage() {
  const { t } = useI18n();
  const [panel, setPanel] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<RoomCredentials | null>(null);
  const [room, setRoom] = useState<RoomState | null>(null);
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [status, setStatus] = useState('Choose a room');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [settingsEntry, setSettingsEntry] = useState<{ code: string; revision: number; value: RoomSettings } | null>(null);
  const [clock, setClock] = useState({ now: 0, offset: 0 });
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
          if (message.viewer_left) {
            for (const storageName of ['sessionStorage', 'localStorage'] as const) {
              try {
                const storage = window[storageName];
                const saved = storage.getItem(`poker-room:${credentials.code}`);
                if (saved && JSON.parse(saved).token === credentials.token) storage.removeItem(`poker-room:${credentials.code}`);
              } catch { /* Storage is optional. */ }
            }
            pending.current = null;
            latest.current = null;
            setCredentials(null); setRoom(null); setBusy(false); setStatus('Choose a room');
            window.history.replaceState(null, '', '/friends');
            return;
          }
          setClock({ now: Date.now(), offset: message.server_now - Date.now() });
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
          setError('This seat is no longer available. Check the invitation or join the room again.');
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

  useEffect(() => {
    if (!room?.deadline_at) return;
    const timer = setInterval(() => setClock((value) => ({ ...value, now: Date.now() })), 250);
    return () => clearInterval(timer);
  }, [room?.deadline_at]);

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
  const everyoneReady = Boolean(room && room.members.length >= 2 && room.members.filter((member) => !member.sitting_out).length >= 2 && room.members.filter((member) => !member.sitting_out).every((member) => member.ready && member.connected));

  const settings = room?.settings ?? { starting_stack: 1000, small_blind: 5, big_blind: 10, turn_seconds: 30 };
  const editedSettings = settingsEntry && settingsEntry.code === room?.code && settingsEntry.revision === room?.revision ? settingsEntry.value : settings;
  const validSettings = Object.values(editedSettings).every(Number.isInteger)
    && editedSettings.small_blind >= 1 && editedSettings.small_blind <= 10000
    && editedSettings.big_blind > editedSettings.small_blind && editedSettings.big_blind <= 20000
    && editedSettings.starting_stack >= Math.max(100, 20 * editedSettings.big_blind)
    && editedSettings.starting_stack <= 1000000
    && editedSettings.turn_seconds >= 10 && editedSettings.turn_seconds <= 120;
  const editSetting = (key: keyof RoomSettings, value: number) => {
    if (room) setSettingsEntry({ code: room.code, revision: room.revision, value: { ...editedSettings, [key]: value } });
  };

  const secondsLeft = room?.deadline_at ? Math.max(0, Math.ceil((room.deadline_at - clock.now - clock.offset) / 1000)) : null;
  // deadline_at includes the quiet phase; never start a new timer on reconnect.
  const visibleSecondsLeft = secondsLeft !== null && secondsLeft <= settings.turn_seconds ? secondsLeft : null;
  const turnTimer = hand?.current_player_id && !hand.result && visibleSecondsLeft !== null
    ? { playerId: hand.current_player_id, remaining: visibleSecondsLeft, duration: settings.turn_seconds } : null;


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

  const lobby = (
<section className="control-panel room-lobby">
                <p className="saved-room">{t("Saved on this server · reconnect after a restart")}</p>

                <h2>{t(betweenHands ? 'Ready for the next hand?' : 'Players at the table')}</h2>

                <ul>{room?.members.map((member) => <li key={member.player_id}><div><strong>{member.name}{t(member.player_id === room.viewer_id ? ' (you)' : '')}</strong><span>{t(member.player_id === room.host_id ? 'Host · ' : '')}{t(member.connected ? 'Connected' : 'Disconnected')}</span></div><em>{t(member.sitting_out ? 'Sitting out' : member.ready ? 'Ready' : betweenHands ? 'Waiting' : 'Playing')}</em></li>)}</ul>
                <button disabled={busy || !connected || (Boolean(me?.sitting_out) && !betweenHands)} onClick={() => send('sit_out', { sit_out: !me?.sitting_out })}>{t(me?.sitting_out ? 'Return to table' : 'Sit out')}</button>
                {me?.sitting_out ? <p>{t("You are sitting out. Current-hand decisions use check/fold automatically; return between hands.")}</p> : null}
                {betweenHands ? <><button disabled={busy || !connected || Boolean(me?.sitting_out)} onClick={() => send('ready', { ready: !me?.ready })}>{t(me?.ready ? 'Not ready' : "I'm ready")}</button>{isHost ? <button className="primary-button" disabled={busy || !connected || !everyoneReady} onClick={() => send('start')}>{t(hand ? 'Deal next hand' : 'Deal first hand')}</button> : <p>{t("The host deals when everyone is ready.")}</p>}</> : <p>{hand?.players.find((player) => player.id === hand.current_player_id)?.name}{t("'s turn. Streets advance automatically.")}</p>}
                <p className="room-note">{t("Blinds ")}{t(settings.small_blind)}/{t(settings.big_blind)}{t(" · Starting stack ")}{t(settings.starting_stack)}{t(". Virtual training chips: stacks below ")}{t(settings.big_blind)}{t(" receive ")}{t(settings.starting_stack)}{t(" extra chips between hands. Players can join between hands. Reopen this link in the same browser to restore your seat.")}</p>
                <p className="room-note">{t("After {0} quiet seconds, the {1}-second countdown starts. The clock continues after disconnect; timeout checks or folds, then sits out.").replace('{0}', String(room?.turn_grace_seconds ?? 10)).replace('{1}', String(settings.turn_seconds))}</p>
                              {!hand && isHost ? <details className="room-settings-disclosure"><summary>{t("Table settings")}</summary><fieldset className="room-settings" disabled={busy || !connected}>
                  <legend>{t("Table settings")}</legend>
                  <label>{t("Starting stack")}<input type="number" min={100} max={1000000} step={1} value={editedSettings.starting_stack} onChange={(event) => editSetting('starting_stack', Number(event.target.value))} /></label>
                  <label>{t("Small blind")}<input type="number" min={1} max={10000} step={1} value={editedSettings.small_blind} onChange={(event) => editSetting('small_blind', Number(event.target.value))} /></label>
                  <label>{t("Big blind")}<input type="number" min={2} max={20000} step={1} value={editedSettings.big_blind} onChange={(event) => editSetting('big_blind', Number(event.target.value))} /></label>
                  <label>{t("Countdown seconds")}<input type="number" min={10} max={120} step={1} value={editedSettings.turn_seconds} onChange={(event) => editSetting('turn_seconds', Number(event.target.value))} /></label>
                  <button disabled={!validSettings} onClick={() => send('settings', { settings: editedSettings })}>{t("Apply settings")}</button>
                  <small>{t("At least 20 big blinds in the starting stack. Applying changes clears everyone's readiness. Settings lock after the first deal.")}</small>
                </fieldset></details> : null}
</section>
  );

  return (
    <main className={`app-shell play-shell room-shell ${hand ? 'room-in-hand' : ''}`}>
      <AppHeader><span className={`connection-state ${connected ? 'is-connected' : ''}`} role="status" aria-label={t(status)} title={t(status)}>{t(status)}</span></AppHeader>
      <nav className="play-modes" aria-label={t('Game mode')}><Link href="/">{t('AI training')}</Link><Link href="/friends" aria-current="page">{t('Play with friends')}</Link><Link href="/practice">{t('Practice')}</Link></nav>
      {error ? <div className="error-banner" role="alert"><span>{t(error)}</span><button onClick={() => setError(null)}>{t("Dismiss")}</button></div> : null}
      {!credentials ? (
        <section className="room-entry control-panel">
          <h2>{t("Your private poker table")}</h2>
          <p>{t("Create a room and share its invitation. Bring 2–6 players, mark everyone ready, then deal.")}</p>
          <label>{t("Your name")}<input autoComplete="nickname" maxLength={24} value={name} onChange={(event) => setName(event.target.value)} placeholder="Roman" /></label>
          <button className="primary-button" disabled={busy || !name.trim()} onClick={() => enter(false)}>{t("Create room")}</button>
          <div className="room-join"><label>{t("Room code")}<input maxLength={8} value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} placeholder={t("Invitation code")} /></label><button disabled={busy || !name.trim() || code.trim().length !== 8} onClick={() => enter(true)}>{t("Join room")}</button></div>
          <p className="room-note">{t("Local preview. Friends on other networks will need the hosting stage. Rooms, seats and hands are saved on this server.")}</p>
        </section>
      ) : (
        <>
          <section className="room-toolbar control-panel">
            <div><span className="eyebrow">{t('Room')} {credentials.code}</span><strong>{me?.name ?? t('Restoring your seat')} · {room?.members.length ?? 1}/6</strong></div>
            <button onClick={copyInvite}>{t(copied ? 'Link copied' : 'Copy invitation')}</button>
            <details className="room-menu"><summary aria-label={t('Table options')}>⋯</summary><div className="room-menu-content">
              <label>{t('Invitation link')}<input className="invite-field" readOnly value={typeof window === 'undefined' ? '' : `${window.location.origin}/friends?room=${credentials.code}`} /></label>
              <button onClick={reset}>{t('Close table')}</button><button disabled={busy || !connected} onClick={() => send('leave')}>{t('Leave room')}</button>
            </div></details>
          </section>
          {hand ? <div className="table-meta"><span>{t(hand.street)} · {hand.players.length} {t('players')}</span><span>{t('Blinds')} {settings.small_blind} / {settings.big_blind}</span></div> : null}
          <section className="game-layout">
            <div className="table-column">
              <PokerTable emptyStack={settings.starting_stack} hand={hand} seatCount={hand?.players.length ?? Math.max(2, room?.members.length ?? 2)} viewerId={room?.viewer_id} turnTimer={turnTimer} />
              {hand ? <ActionPanel analysis={null} hand={hand} isLoading={busy} blocked={!connected || Boolean(me?.sitting_out)} waitingLabel={!connected ? t(status) : me?.sitting_out ? t("Sitting out") : undefined} viewerId={room?.viewer_id} trainingControls={false} secondsLeft={visibleSecondsLeft} tools={<><button aria-haspopup="dialog" onClick={() => setPanel('players')}>{t('Players')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('history')}>{t('History')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('archive')}>{t('Hand archive')} ↑</button></>} onAction={action} onAdvance={() => {}} onAnalyze={() => {}} onStartHand={() => {}} /> : null}
            </div>
            <PanelSidebar notice={visibleSecondsLeft !== null ? <p className={`sheet-timer ${visibleSecondsLeft !== null && visibleSecondsLeft <= 10 ? "urgent" : ""}`} role="timer">{t("Time remaining")}: {visibleSecondsLeft}s</p> : null} collapseOnMobile={Boolean(hand)} active={panel} onClose={() => setPanel(null)} panels={[
              { id: 'players', title: t('Players'), content: lobby },
              { id: 'history', title: t('History'), content: <HandHistory hand={hand} /> },
              { id: 'archive', title: t('Hand archive'), content: <HandArchive key={`${credentials.code}:${credentials.player_id}`} credentials={credentials} completedHandId={hand?.result ? hand.hand_id : null} /> },
            ]} />
          </section>
        </>
      )}
    </main>
  );
}
