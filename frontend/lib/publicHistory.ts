export function checkedHistory(value:unknown):any[] {
  if(!Array.isArray(value)||value.some(row=>!row||typeof row!=="object"||typeof row.amount!=="number"||!Number.isFinite(row.amount)||row.amount<0)) {
    throw new Error("Payment history response is unavailable or invalid.");
  }
  return value;
}
