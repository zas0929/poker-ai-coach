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

type SettingsDraft = Record<'starting_stack' | 'small_blind' | 'big_blind' | 'turn_seconds', string>;

export default function FriendsPage() {
  const { t } = useI18n();
  const [panel, setPanel] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<RoomCredentials | null>(null);
  const [room, setRoom] = useState<RoomState | null>(null);
  const [name, setName] = useState('');
  const [buyIn, setBuyIn] = useState('400');
  const [topUp, setTopUp] = useState('400');
  const [topUpNotice, setTopUpNotice] = useState<number | null>(null);
  const [autoDeal, setAutoDeal] = useState(true);
  const [creationDraft, setCreationDraft] = useState<SettingsDraft>({ starting_stack: '400', small_blind: '1', big_blind: '2', turn_seconds: '30' });
  const creationSettings: RoomSettings = { starting_stack: Number(creationDraft.starting_stack), small_blind: Number(creationDraft.small_blind), big_blind: Number(creationDraft.big_blind), turn_seconds: Number(creationDraft.turn_seconds), auto_deal: autoDeal };
  const validCreation = Object.values(creationDraft).every(value => value.trim() !== '' && Number.isInteger(Number(value))) && creationSettings.small_blind >= 1 && creationSettings.small_blind <= 10000 && creationSettings.big_blind > creationSettings.small_blind && creationSettings.big_blind <= 20000 && creationSettings.starting_stack >= Math.max(100, 20 * creationSettings.big_blind) && creationSettings.starting_stack <= 1000000 && creationSettings.turn_seconds >= 10 && creationSettings.turn_seconds <= 120;
  const validBuyIn = buyIn.trim() !== '' && Number.isInteger(Number(buyIn)) && Number(buyIn) >= 2 && Number(buyIn) <= 1000000;
  const [code, setCode] = useState('');
  const [invited, setInvited] = useState(false);
  const [status, setStatus] = useState('Choose a room');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [settingsEntry, setSettingsEntry] = useState<{ code: string; baseline: string; value: SettingsDraft } | null>(null);
  const [clock, setClock] = useState({ now: 0, offset: 0 });
  const socket = useRef<WebSocket | null>(null);
  const latest = useRef<RoomState | null>(null);
  const pending = useRef<{ id: string; payload: string; closePanel: boolean; topUpAmount: number | null } | null>(null);
  const commandTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const entering = useRef(false);

  useEffect(() => {
    const invitation = new URLSearchParams(window.location.search).get('room')?.trim().toUpperCase();
    if (invitation) {
      // URL and local storage are available only after browser hydration.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCode(invitation);
      setInvited(true);
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
        } else if (message.type === 'ack' && pending.current && pending.current.id === message.command_id) {
          if (pending.current.closePanel) setPanel(null);
          if (pending.current.topUpAmount !== null) setTopUpNotice(pending.current.topUpAmount);
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
    if (!room?.deadline_at && !room?.next_hand_at) return;
    const timer = setInterval(() => setClock((value) => ({ ...value, now: Date.now() })), 250);
    return () => clearInterval(timer);
  }, [room?.deadline_at, room?.next_hand_at]);

  const enter = async (join: boolean) => {
    if (entering.current || !validBuyIn || (!join && !validCreation)) return;
    entering.current = true;
    setBusy(true);
    setError(null);
    try {
      const next = await enterRoom(name.trim(), join ? code.trim().toUpperCase() : undefined, Number(buyIn), join ? undefined : creationSettings);
      try { sessionStorage.setItem(`poker-room:${next.code}`, JSON.stringify(next)); } catch { /* Keep this session. */ }
      try { localStorage.setItem(`poker-room:${next.code}`, JSON.stringify(next)); } catch { /* Keep this session. */ }
      window.history.replaceState(null, '', `/friends?room=${next.code}`);
      setCode(next.code);
      setCredentials(next);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not enter room.'); }
    finally { setBusy(false); entering.current = false; }
  };

  const send = (kind: string, values: Record<string, unknown> = {}, options: { closePanel?: boolean } = {}) => {
    if (pending.current || socket.current?.readyState !== WebSocket.OPEN || !latest.current) return;
    const id = crypto.randomUUID();
    const payload = JSON.stringify({ command_id: id, revision: latest.current.revision, kind, ...values });
    pending.current = { id, payload, closePanel: Boolean(options.closePanel), topUpAmount: kind === 'top_up' ? Number(values.amount) : null };
    setTopUpNotice(null);
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
  const canTopUp = betweenHands || !hand?.players.some(player => player.id === room?.viewer_id);
  const connected = status === 'Connected';
  const isHost = room?.viewer_id === room?.host_id;
  const everyoneReady = Boolean(room && room.members.length >= 2 && room.members.filter((member) => !member.sitting_out && member.stack >= room.settings.big_blind).length >= 2 && room.members.filter((member) => !member.sitting_out && member.stack >= room.settings.big_blind).every((member) => member.ready && member.connected));

  const settings = room?.settings ?? { starting_stack: 400, small_blind: 1, big_blind: 2, turn_seconds: 30, auto_deal: true };
  const settingsBaseline = JSON.stringify(settings);
  const editedDraft: SettingsDraft = settingsEntry && settingsEntry.code === room?.code && settingsEntry.baseline === settingsBaseline
    ? settingsEntry.value : { starting_stack: String(settings.starting_stack), small_blind: String(settings.small_blind), big_blind: String(settings.big_blind), turn_seconds: String(settings.turn_seconds) };
  const editedSettings: RoomSettings = { starting_stack: Number(editedDraft.starting_stack), small_blind: Number(editedDraft.small_blind), big_blind: Number(editedDraft.big_blind), turn_seconds: Number(editedDraft.turn_seconds), auto_deal: settings.auto_deal };
  const validSettings = Object.values(editedDraft).every(value => value.trim() !== '' && Number.isInteger(Number(value)))
    && editedSettings.small_blind >= 1 && editedSettings.small_blind <= 10000
    && editedSettings.big_blind > editedSettings.small_blind && editedSettings.big_blind <= 20000
    && editedSettings.starting_stack >= Math.max(100, 20 * editedSettings.big_blind)
    && editedSettings.starting_stack <= 1000000
    && editedSettings.turn_seconds >= 10 && editedSettings.turn_seconds <= 120;
  const editSetting = (key: keyof SettingsDraft, value: string) => {
    if (room) setSettingsEntry({ code: room.code, baseline: settingsBaseline, value: { ...editedDraft, [key]: value } });
  };

  const secondsLeft = room?.deadline_at ? Math.max(0, Math.ceil((room.deadline_at - clock.now - clock.offset) / 1000)) : null;
  // deadline_at includes the quiet phase; never start a new timer on reconnect.
  const nextHandSeconds = room?.next_hand_at ? Math.max(0, Math.ceil((room.next_hand_at - clock.now - clock.offset) / 1000)) : null;
  const autoDealPlayers = room?.members.filter(member => !member.sitting_out && member.stack >= settings.big_blind) ?? [];
  const autoDealStatus = betweenHands && settings.auto_deal
    ? nextHandSeconds !== null ? t('Next hand in {0}s').replace('{0}', String(nextHandSeconds))
      : autoDealPlayers.length < 2 ? t('Waiting for 2 players with chips')
      : autoDealPlayers.some(member => !member.connected) ? t('Waiting for players to reconnect')
      : autoDealPlayers.some(member => !member.ready) ? t('Waiting for all players to be ready')
      : t('Preparing the next hand…')
    : undefined;
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
    setBusy(false); setError(null); setStatus('Choose a room'); setCode(''); setInvited(false);
    window.history.replaceState(null, '', '/friends');
  };

  const lobby = (
<section className="control-panel room-lobby">
                <p className="saved-room">{t("Saved on this server · reconnect after a restart")}</p>

                <h2>{t(betweenHands ? 'Ready for the next hand?' : 'Players at the table')}</h2>

                <ul>{room?.members.map((member) => <li key={member.player_id}><div><strong>{member.name}{t(member.player_id === room.viewer_id ? ' (you)' : '')}</strong><span>{t(member.player_id === room.host_id ? 'Host · ' : '')}{t(member.connected ? 'Connected' : 'Disconnected')}</span></div><b>{member.stack}</b><em>{t(member.sitting_out ? 'Sitting out' : member.ready ? 'Ready' : betweenHands ? 'Waiting' : 'Playing')}</em></li>)}</ul>
                <div className="lobby-hand-controls">
                  {betweenHands ? <button className={!me?.ready ? 'primary-button' : undefined} disabled={busy || !connected || Boolean(me?.sitting_out)} onClick={() => send('ready', { ready: !me?.ready }, { closePanel: true })}>{t(me?.ready ? 'Not ready' : "I'm ready")}</button> : null}
                  <button className={me?.sitting_out ? 'primary-button' : undefined} disabled={busy || !connected || (Boolean(me?.sitting_out) && !betweenHands)} onClick={() => send('sit_out', { sit_out: !me?.sitting_out }, { closePanel: true })}>{t(me?.sitting_out ? 'Return to table' : 'Sit out')}</button>
                </div>
                {error ? <p role="alert" className="top-up-error">{t(error)}</p> : null}
                {topUpNotice !== null ? <p role="status" className="top-up-success">{t('Added {0} chips.').replace('{0}', String(topUpNotice))}</p> : null}
                {canTopUp ? <div className="top-up-controls"><label>{t('Add chips')}<input type="number" inputMode="numeric" min={1} max={1000000 - (me?.stack ?? 0)} value={topUp} onChange={event => setTopUp(event.target.value)} /></label><button disabled={busy || !connected || topUp.trim() === '' || !Number.isInteger(Number(topUp)) || Number(topUp) <= 0 || (me?.stack ?? 0) + Number(topUp) > 1000000} onClick={() => send('top_up', { amount: Number(topUp) })}>{t('Add chips')}</button></div> : null}
                {me?.sitting_out ? <p>{t("You are sitting out. Current-hand decisions use check/fold automatically; return between hands.")}</p> : null}
                <p>{autoDealStatus ?? t(settings.auto_deal ? 'Automatic hands enabled. Unready or sit out to pause.' : 'The host deals when everyone is ready.')}</p>
                <p className="room-note">{t("Blinds ")}{t(settings.small_blind)}/{t(settings.big_blind)} · {t('Virtual chips only. Choose your buy-in and add chips between hands. No automatic refills.')}</p>
                <p className="room-note">{t("After {0} quiet seconds, the {1}-second countdown starts. The clock continues after disconnect; timeout checks or folds, then sits out.").replace('{0}', String(room?.turn_grace_seconds ?? 10)).replace('{1}', String(settings.turn_seconds))}</p>
                              {!hand && isHost ? <details className="room-settings-disclosure"><summary>{t("Table settings")}</summary><fieldset className="room-settings" disabled={busy || !connected}>
                  <legend>{t("Table settings")}</legend>
                  <label>{t("Starting stack")}<input type="number" min={100} max={1000000} step={1} value={editedDraft.starting_stack} onChange={(event) => editSetting('starting_stack', event.target.value)} /></label>
                  <label>{t("Small blind")}<input type="number" min={1} max={10000} step={1} value={editedDraft.small_blind} onChange={(event) => editSetting('small_blind', event.target.value)} /></label>
                  <label>{t("Big blind")}<input type="number" min={2} max={20000} step={1} value={editedDraft.big_blind} onChange={(event) => editSetting('big_blind', event.target.value)} /></label>
                  <label>{t("Countdown seconds")}<input type="number" min={10} max={120} step={1} value={editedDraft.turn_seconds} onChange={(event) => editSetting('turn_seconds', event.target.value)} /></label>
                  <button disabled={!validSettings} onClick={() => send('settings', { settings: editedSettings })}>{t("Apply settings")}</button>
                  <small>{t("At least 20 big blinds in the starting stack. Applying changes clears everyone's readiness. Settings lock after the first deal.")}</small>
                </fieldset></details> : null}
</section>
  );

  return (
    <main className={`app-shell play-shell room-shell ${hand ? 'room-in-hand' : ''}`}>
      <AppHeader><span className={`connection-state ${connected ? 'is-connected' : ''}`} role="status" aria-label={t(status)} title={t(status)}>{t(status)}</span></AppHeader>
      <div className="room-navigation">
        <nav className="play-modes" aria-label={t('Game mode')}><Link href="/">{t('AI training')}</Link><Link href="/friends" aria-current="page">{t('Play with friends')}</Link><Link href="/practice">{t('Practice')}</Link></nav>
        {credentials ? (<section className="room-toolbar control-panel">
            <div><span className="eyebrow">{t('Room')} {credentials.code}</span><strong>{me?.name ?? t('Restoring your seat')} · {room?.members.length ?? 1}/6</strong></div>
            <button className="room-copy-invite" onClick={copyInvite} aria-label={t(copied ? 'Link copied' : 'Copy invitation')} title={t(copied ? 'Link copied' : 'Copy invitation')}><span className="room-invite-label">{t(copied ? 'Link copied' : 'Copy invitation')}</span><span className="room-invite-icon" aria-hidden="true">{copied ? '✓' : '⧉'}</span></button>
            <details className="room-menu"><summary aria-label={t('Table options')}>⋯</summary><div className="room-menu-content">
              <label>{t('Invitation link')}<input className="invite-field" readOnly value={typeof window === 'undefined' ? '' : `${window.location.origin}/friends?room=${credentials.code}`} /></label>
              <button onClick={reset}>{t('Close table')}</button><button disabled={busy || !connected} onClick={() => send('leave')}>{t('Leave room')}</button>
            </div></details>
          </section>) : null}
      </div>
      {error ? <div className="error-banner" role="alert"><span>{t(error)}</span><button onClick={() => setError(null)}>{t("Dismiss")}</button></div> : null}
      {!credentials ? (
        <section className="room-entry control-panel">
          <h2>{t("Your private poker table")}</h2>
          <p>{t("Create a room and share its invitation. Bring 2–6 players, mark everyone ready, then deal.")}</p>
          <label>{t("Your name")}<input autoComplete="nickname" maxLength={24} value={name} onChange={(event) => setName(event.target.value)} placeholder="Roman" /></label>
          {!invited ? <details className="creation-settings"><summary>{t('Table settings')}</summary><fieldset disabled={busy}>
            {([['starting_stack', 'Starting stack'], ['small_blind', 'Small blind'], ['big_blind', 'Big blind'], ['turn_seconds', 'Countdown seconds']] as const).map(([key, label]) => <label key={key}>{t(label)}<input type="number" inputMode="numeric" value={creationDraft[key]} onChange={event => setCreationDraft(old => ({ ...old, [key]: event.target.value }))} /></label>)}
            <label className="auto-deal-option"><input type="checkbox" checked={autoDeal} onChange={event => setAutoDeal(event.target.checked)} />{t('Automatically ready and deal next hands')}</label>
            <p>{t('An eight-second pause between hands leaves time to review results or pause readiness.')}</p>
          </fieldset></details> : null}
          <label>{t('Buy-in chips')}<input type="number" inputMode="numeric" min={2} max={1000000} value={buyIn} onChange={event => setBuyIn(event.target.value)} /></label>
          <button className="primary-button" disabled={busy || !validBuyIn || (!invited && !validCreation) || !name.trim() || (invited && code.trim().length !== 8)} onClick={() => enter(invited)}>{t(invited ? "Join room" : "Create room")}</button>
          <div className="room-join"><label>{t("Room code")}<input maxLength={8} value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} placeholder={t("Invitation code")} /></label>{!invited ? <button disabled={busy || !validBuyIn || !name.trim() || code.trim().length !== 8} onClick={() => enter(true)}>{t("Join room")}</button> : null}</div>
          <p className="room-note">{t("Local preview. Friends on other networks will need the hosting stage. Rooms, seats and hands are saved on this server.")}</p>
        </section>
      ) : (
        <>
          {hand ? <div className="table-meta"><span>{t(hand.street)} · {hand.players.length} {t('players')}</span><span>{t('Blinds')} {settings.small_blind} / {settings.big_blind}</span></div> : null}
          <section className="game-layout">
            <div className="table-column">
              <PokerTable emptyStack={settings.starting_stack} hand={hand} seatCount={hand?.players.length ?? Math.max(2, room?.members.length ?? 2)} viewerId={room?.viewer_id} turnTimer={turnTimer} />
              <ActionPanel pausedActions={me?.sitting_out ? <button className="primary-button" disabled={busy || !connected || !betweenHands} title={!betweenHands ? t('You can return after this hand finishes.') : undefined} onClick={() => send('sit_out', { sit_out: false })}>{t('Return to table')}</button> : undefined} betweenActions={betweenHands ? <div className="room-hand-controls"><button disabled={busy || !connected || Boolean(me?.sitting_out)} onClick={() => send('ready', { ready: !me?.ready })}>{t(me?.ready ? 'Not ready' : "I'm ready")}</button>{isHost ? <button className="primary-button" disabled={busy || !connected || !everyoneReady} onClick={() => send('start')}>{t(hand ? 'Deal next hand' : 'Deal first hand')}</button> : null}</div> : null} analysis={null} stack={canTopUp ? me?.stack : undefined} hand={hand} isLoading={busy} blocked={!connected || Boolean(me?.sitting_out)} waitingLabel={!connected ? t(status) : me?.sitting_out ? t(betweenHands ? "Sitting out" : "Return after this hand") : autoDealStatus} viewerId={room?.viewer_id} trainingControls={false} secondsLeft={visibleSecondsLeft} tools={<><button aria-haspopup="dialog" onClick={() => setPanel('players')}>{t('Players')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('history')}>{t('History')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('archive')}>{t('Hand archive')} ↑</button></>} onAction={action} onAdvance={() => {}} onAnalyze={() => {}} onStartHand={() => {}} />
            </div>
            <PanelSidebar notice={visibleSecondsLeft !== null ? <p className={`sheet-timer ${visibleSecondsLeft !== null && visibleSecondsLeft <= 10 ? "urgent" : ""}`} role="timer">{t("Time remaining")}: {visibleSecondsLeft}s</p> : null} active={panel} onClose={() => setPanel(null)} panels={[
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
