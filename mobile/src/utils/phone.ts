/**
 * 35M R2 (item 4): one phone-masking convention, shared by the guest list
 * and the guest pass artwork/share message. Format: first 4 digits, a
 * bullet gap, last 4 digits — `0300 1234567` → `0300 ••• 4567`. Numbers
 * shorter than 8 digits are returned unchanged (nothing meaningful to
 * mask; the raw value is still not a full personal number in practice).
 * Test pins: ui-35h (`maskPhone` in GuestsScreen) + ui-35j Q/R keep the
 * call sites; this helper is the single implementation.
 */
export function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 8) return phone;
  return `${digits.slice(0, 4)} ••• ${digits.slice(-4)}`;
}
