#!/bin/bash
# 测试报表相关接口，运行前确保 JimuReport 已启动
# 用法：./scripts/test_report_curl.sh

BASE="http://127.0.0.1:8085"
echo "=== 1. 测试 /undefined 兜底 ==="
code=$(curl -s -o /tmp/undef.json -w "%{http_code}" "$BASE/undefined")
echo "HTTP $code"
[ "$code" = "200" ] && echo "OK" || echo "FAIL (应为 200)"

echo ""
echo "=== 2. 测试 view 页面 baseFull ==="
basefull=$(curl -s "$BASE/jmreport/view/1350035590569136128" | grep -o 'baseFull = [^;]*' | head -1)
echo "baseFull: $basefull"
if echo "$basefull" | grep -q "127.0.0.1:8085"; then
  echo "OK (baseFull 已正确注入)"
else
  echo "FAIL (baseFull 应为 http://127.0.0.1:8085，需重启服务)"
fi

echo ""
echo "=== 3. 测试 list 页面 baseFull ==="
listbase=$(curl -s "$BASE/jmreport/list?menuType=984272091947253760" | grep -o 'baseFull = [^;]*' | head -1)
echo "list baseFull: $listbase"
if echo "$listbase" | grep -q "127.0.0.1:8085"; then
  echo "OK (list 页面 baseFull 已正确注入)"
else
  echo "FAIL (list 页面 baseFull 未注入，需重启服务)"
fi

echo ""
echo "=== 4. 测试 /jmreport/show (报表数据接口) ==="
code=$(curl -s -o /tmp/show.json -w "%{http_code}" "$BASE/jmreport/show?id=1350035590569136128")
echo "HTTP $code"
[ "$code" = "200" ] && echo "OK" || echo "FAIL"
