/**
 * Patients page statistics, derived from the list the page already fetched.
 *
 * No extra request: GET /patients/ returns every row for the tenant, so these are
 * arithmetic over it and can never disagree with the table below.
 *
 * "Recognised" is not a stored field. A contact carries `history`, which the agent
 * fills in when it deals with that caller, so a contact with history has been
 * recognised on a call and one without has not been yet. The Status column is derived
 * from the same field ("Returning" / "New"), which is why the two cards and the column
 * always agree. The two groups are complementary, so they sum to the total.
 */

const monthKey = (d) => d.getFullYear() * 12 + d.getMonth();

/**
 * @param list rows as produced by formatPatient, plus `createdAt` and `recognised`.
 */
export function derivePatientStats(list = []) {
  const now = new Date();
  const thisMonth = monthKey(now);
  const lastMonth = thisMonth - 1;

  let recognised = 0;
  let newThisMonth = 0;
  let newLastMonth = 0;

  for (const p of list) {
    if (p.recognised) recognised += 1;
    if (!p.createdAt) continue; // cannot place an undated row in a month
    const k = monthKey(new Date(p.createdAt));
    if (k === thisMonth) newThisMonth += 1;
    else if (k === lastMonth) newLastMonth += 1;
  }

  const total = list.length;
  const share = (n) => (total > 0 ? Math.round((n / total) * 1000) / 10 : 0);

  return {
    total,
    recognised,
    recognisedShare: share(recognised),
    notRecognised: total - recognised,
    notRecognisedShare: share(total - recognised),
    newThisMonth,
    newLastMonth,
    // null, not 0: with nothing added last month a percentage change is undefined, and
    // any figure shown there would be invented. The card omits the line.
    newChangePct:
      newLastMonth > 0 ? Math.round(((newThisMonth - newLastMonth) / newLastMonth) * 100) : null,
  };
}
