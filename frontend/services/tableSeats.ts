import type { HandState, Player } from '@/types/poker';
import type { RoomMember } from '@/services/roomApi';

export function tableSeats(hand: HandState | null, seatCount: number, viewerId = 'hero', members?: RoomMember[]) {
  let roster: { player: Player; waiting: boolean }[] = hand?.players.map(player => ({ player, waiting: false })) ?? [];
  if (members) {
    roster = [...members].sort((a, b) => a.seat - b.seat).map(member => {
      const player = hand?.players.find(p => p.id === member.player_id);
      return { player: player ?? { id: member.player_id, name: member.name, stack: member.stack,
        position: 'waiting', cards: [], status: 'active' as const, current_bet: 0 }, waiting: !player };
    });
    // A departing participant still belongs to the current hand until it settles.
    if (hand && !hand.result) for (const player of hand.players) {
      if (!roster.some(seat => seat.player.id === player.id)) roster.push({ player, waiting: false });
    }
    seatCount = Math.max(2, roster.length);
  }
  const slotsByCount: Record<number, string[]> = {
    2: ['bottom', 'top'], 3: ['bottom', 'left', 'right'],
    4: ['bottom', 'top-left', 'top', 'top-right'],
    5: ['bottom', 'left', 'top-left', 'top-right', 'right'],
    6: ['bottom', 'left', 'top-left', 'top', 'top-right', 'right'],
  };
  const slots = slotsByCount[seatCount] ?? slotsByCount[2];
  const offset = Math.max(0, roster.findIndex(seat => seat.player.id === viewerId));
  return slots.map((slot, index) => {
    const entry = roster.length ? roster[(index + offset) % Math.max(roster.length, slots.length)] : undefined;
    return { slot, player: entry?.player, waiting: entry?.waiting ?? false, label: `Seat ${index + 1}` };
  });
}
