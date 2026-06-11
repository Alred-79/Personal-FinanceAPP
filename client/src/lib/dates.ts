/** Returns the ISO YYYY-MM-DD start and end of the current week, Sunday to Saturday. */
export function currentWeekRange(): { startDate: string; endDate: string } {
  const today = new Date();
  const start = new Date(today);
  start.setDate(today.getDate() - today.getDay());
  const end = new Date(today);
  end.setDate(today.getDate() + (6 - today.getDay()));
  return {
    startDate: start.toISOString().split("T")[0],
    endDate: end.toISOString().split("T")[0],
  };
}
