/**
 * 将接口/异常中的任意提示值转为可展示字符串，避免 new Error(obj) 与 Toast 出现 "[object Object]"。
 * @param {*} v
 * @param {string} [fallback]
 */
function errText(v, fallback) {
  const fb =
    fallback !== undefined && fallback !== null && fallback !== ""
      ? fallback
      : "";
  if (v == null || v === "") return fb;
  if (typeof v === "string") {
    const s = v.trim();
    if (s === "[object Object]" || s === "undefined") return fb || "请稍后重试";
    return v;
  }
  try {
    return JSON.stringify(v);
  } catch (e) {
    return String(v);
  }
}

module.exports = { errText };
