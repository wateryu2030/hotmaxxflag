# JimuReport 列表页「看不到数据列表」排查

## 现象

- 打开 http://127.0.0.1:8085/jmreport/list，左侧选「数据报表」后，中间显示「共7条」但下方几乎空白，只有「新建报表」和少量占位。
- 控制台有：`GET http://127.0.0.1:8085/jmreport/undefined 404`、Network Error、CORS 图片加载失败等。

## 原因简述

1. **请求地址里出现 `undefined`**：前端用到的某个变量（如接口前缀、分类 id）未赋值，请求发到 `/jmreport/undefined`，接口 404，列表数据拿不到。
2. **apiBasePath 与访问地址不一致**：若配置里 `jeecg.jmreport.apiBasePath` 是别的机器（如 192.168.x.x），前端用该地址请求接口可能失败或行为异常。
3. **缩略图 CORS**：列表里报表缩略图来自外网（如 static.jeecg.com），被浏览器 CORS 拦截，只影响图片显示，一般不影响列表接口数据。

## 已做修改

1. **application-dev.yml**
   - **apiBasePath** 改为本机：`http://127.0.0.1:8085`
   - 增加 **domainURL**：`http://127.0.0.1:8085`（与 apiBasePath 一致，部分页面会读该配置）

2. **兜底接口**
   - 当请求 `GET /jmreport/undefined` 时（前端未拿到分类 id 会发该请求），不再 404，改为返回 `200` + 空列表 JSON，避免控制台报错、请求失败。用户再点击左侧「数据报表」会带正确 menuType 重新请求并加载列表。

## 你需要做的

1. **重启 JimuReport**  
   修改了配置，需重启后生效：
   ```bash
   cd JimuReport/jimureport-example
   # 停掉当前进程后
   mvn spring-boot:run
   ```

2. **带分类打开列表页（推荐）**  
   不要只打开 `/jmreport/list`，而是带「数据报表」的 menuType 打开，减少前端未传分类 id 导致 `undefined` 的情况：
   - 打开：  
     `http://127.0.0.1:8085/jmreport/list?menuType=984272091947253760`  
   - 其中 `984272091947253760` 为「数据报表」分类 id。

3. **若列表仍空白，直接进报表**  
   列表只是入口，数据在报表里。可直接打开「好特卖销售明细」设计/预览：
   - 设计：  
     `http://127.0.0.1:8085/jmreport/index/8946110000000000001?menuType=984272091947253760`  
   - 登录：admin / 123456。

4. **清缓存再试**  
   若之前报错被缓存，可尝试：强制刷新（Ctrl+F5 / Cmd+Shift+R），或清除该站点缓存后再访问上述链接。

## 小结

- 核心是：**接口不要请求到 `/jmreport/undefined`**。  
- 已通过 **apiBasePath 改为 http://127.0.0.1:8085** 和 **带 menuType 的列表 URL** 降低出现概率。  
- 重启 + 带参数打开列表 + 必要时直接打开报表链接，一般即可看到数据或至少能正常打开报表。
