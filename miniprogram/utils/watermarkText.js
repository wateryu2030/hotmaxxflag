/** 全页安全水印文案（截屏溯源，勿含完整 openid） */

function pad2(n) {
  return String(n).padStart(2, "0");
}

function compactTs(d) {
  return (
    d.getFullYear() +
    pad2(d.getMonth() + 1) +
    pad2(d.getDate()) +
    "-" +
    pad2(d.getHours()) +
    pad2(d.getMinutes())
  );
}

function maskPhone(p) {
  const s = String(p == null ? "" : p).replace(/\D/g, "");
  if (s.length >= 11) return s.slice(0, 3) + "****" + s.slice(-4);
  if (s.length >= 7) return "****" + s.slice(-4);
  return s ? "**" : "";
}

function maskOpenid(oid) {
  const s = String(oid || "");
  if (!s) return "";
  if (s.length <= 10) return "…" + s.slice(-4);
  return s.slice(0, 3) + "…" + s.slice(-4);
}

function buildSecurityWatermarkText() {
  const app = getApp();
  const sid = (app && app.globalData && app.globalData.wmSessionKey) || "";
  const ts = compactTs(new Date());
  const hasToken = !!wx.getStorageSync("token");
  const u = (app && app.globalData && app.globalData.userInfo) || null;

  if (!hasToken) {
    return ["HTMA内部数据", "未登录", ts, sid].filter(Boolean).join(" ");
  }

  const parts = ["HTMA内部数据", u && u.id != null ? "UID" + u.id : "UID—"];
  const ph = u && maskPhone(u.phone);
  if (ph) parts.push(ph);
  else {
    const mo = u && maskOpenid(u.openid);
    if (mo) parts.push(mo);
  }
  if (u && u.store_id != null && String(u.store_id).trim()) {
    parts.push("门店" + String(u.store_id).trim());
  }
  if (u && u.role) parts.push(String(u.role).slice(0, 12));
  parts.push(ts, sid);
  return parts.join(" ");
}

module.exports = { buildSecurityWatermarkText };
