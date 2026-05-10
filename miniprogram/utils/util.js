function fmtMoney(n) {
  const x = Number(n);
  if (isNaN(x)) return "—";
  return x.toLocaleString("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function fmtPct(n) {
  const x = Number(n);
  if (isNaN(x)) return "—";
  return x.toFixed(1) + "%";
}

module.exports = { fmtMoney, fmtPct };
