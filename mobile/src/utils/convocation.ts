/**
 * One convocation title line for every student screen (26A A3 / 26F).
 *
 * A convocation name already carries its year ("LGU Convocation 2026"), so
 * blindly appending " · {year}" produced "LGU Convocation 2026 · 2026" on the
 * event, announcements, history, medalist and support headers. Append the year
 * ONLY when the name does not already state it, so the header reads once.
 */
export function convocationLine(
  convocation: { name: string; year: string | number } | null | undefined,
): string | undefined {
  if (!convocation) return undefined;
  const { name, year } = convocation;
  return name.includes(String(year)) ? name : `${name} · ${year}`;
}
