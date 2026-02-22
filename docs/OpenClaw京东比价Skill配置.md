# OpenClaw 比价 Skill 配置

## 一、Skill 已创建

| Skill | 触发词 | 说明 |
|-------|--------|------|
| `htma-jd-price-scrape` | 京东比价、自主比价、爬取京东价格 | Playwright 爬取京东 |
| `htma-pdd-price-compare` | 拼多多比价、设置拼多多比价、申请蚂蚁星球 | 拼多多蚂蚁星球 API |

**核心逻辑**：
- 从 DB 取**具体品名+规格**商品（优先有品牌、规格的）
- 用 `build_search_keyword()` 生成「品牌+品名+规格」空格分隔的**模糊搜索词**
- 在京东搜索页爬取竞品价

## 二、让 OpenClaw 加载本 Skill

### 方式 A：工作区 Skill（推荐）

若将本项目作为 OpenClaw 工作区打开，`/skills` 下的技能会自动加载。

### 方式 B：extraDirs 配置

在 `~/.openclaw/openclaw.json` 的 `skills.load.extraDirs` 中加入本项目 skills 路径：

```json5
{
  "skills": {
    "load": {
      "extraDirs": [
        "/Users/document/好特卖超级仓/数据分析/skills"
      ],
      "watch": true,
      "watchDebounceMs": 250
    }
  }
}
```

### 方式 C：复制到 ~/.openclaw/skills

```bash
cp -r /Users/document/好特卖超级仓/数据分析/skills/htma-jd-price-scrape ~/.openclaw/skills/
```

## 三、执行

| 指令 | 说明 |
|------|------|
| 京东比价 / 自主比价 | 触发京东爬取 |
| 拼多多比价 / 申请蚂蚁星球 | 触发拼多多比价（需先申请 apikey） |

## 四、拼多多全权限自动申请（wateryu2030@gmail.com）

```bash
npm run htma:pdd_apply
```

会打开注册页与 API 页，使用 wateryu2030@gmail.com 完成注册后，将 apikey 填入 `.env` 即可。

全权限配置见 `config/openclaw-htma-full.json`，合并到 `~/.openclaw/openclaw.json`。

## 利用 OpenClaw 自主完成编程（浏览器 + 外设）

若需要 **OpenClaw 自主分析任务、直接调用浏览器和终端** 完成编程（而非仅执行固定脚本），见 **`docs/OpenClaw自主编程-浏览器与外设.md`**，并合并 **`config/openclaw-htma-autonomous.json`** 以开启 browser 与 exec 等工具。
