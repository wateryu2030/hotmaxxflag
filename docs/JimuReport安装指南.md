# JimuReport 安装指南（macOS）

## 一、环境要求

| 依赖 | 版本要求 | 检查命令 |
|------|----------|----------|
| JDK | 17+ | `java -version` |
| Maven | 3.6+ | `mvn -v` |
| MySQL | 5.7+ | `mysql --version` |
| Redis | 可选 | `redis-cli ping` |

---

## 二、环境安装

### 1. 安装 JDK 17（必选）

```bash
# 使用 Homebrew 安装（推荐）
brew install openjdk@17

# 配置环境变量（写入 ~/.zshrc 或 ~/.bash_profile）
echo 'export PATH="/opt/homebrew/opt/openjdk@17/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 2. 安装 Maven（必选）

```bash
brew install maven
```

### 3. 安装 MySQL（必选）

```bash
brew install mysql@5.7
# 或
brew install mysql

brew services start mysql
```

### 4. 安装 Redis（可选）

```bash
brew install redis
brew services start redis
```

---

## 三、JimuReport 安装

### 方式 A：源码运行（推荐，可自定义）

```bash
# 1. 克隆项目
cd ~/Downloads  # 或任意目录
git clone https://github.com/jeecgboot/JimuReport.git
cd JimuReport

# 2. 初始化数据库
# 用 MySQL 客户端执行 db/jimureport.mysql5.7.create.sql
mysql -u root -p < db/jimureport.mysql5.7.create.sql

# 3. 修改配置
# 编辑 jimureport-example/src/main/resources/application-dev.yml
# 修改 spring.datasource 的 url、username、password

# 4. 启动
cd jimureport-example
mvn clean spring-boot:run
```

### 方式 B：Docker 快速运行

参考官方文档：<https://help.jimureport.com/docker.html>

### 方式 C：绿色免安装版（无需 Maven）

- 百度网盘下载：<https://pan.baidu.com/s/1z9VmMz4HCc7GMVbzugetLQ?pwd=xafr>
- 解压后直接运行 jar 或 bat 脚本

---

## 四、配置修改

编辑 `jimureport-example/src/main/resources/application-dev.yml`：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/jimureport?useUnicode=true&characterEncoding=utf8&zeroDateTimeBehavior=convertToNull&useSSL=true&serverTimezone=GMT%2B8
    username: root      # 改为你的 MySQL 用户名
    password: 123456    # 改为你的 MySQL 密码
```

---

## 五、访问地址

| 功能 | 地址 |
|------|------|
| 报表工作台 | http://localhost:8085/jmreport/list |
| 仪表盘设计（BI） | http://localhost:8085/drag/list |
| 默认账号 | admin |
| 默认密码 | 123456 |

---

## 六、数据库连接异常时按此排查

出现「数据库连接异常」时，按顺序做下面 3 步：

### 1. 启动 MySQL

```bash
brew services start mysql
# 或
mysql.server start
```

验证：`mysql -u root -p` 能登录（无密码则直接回车）。

### 2. 创建 jimureport 库并建表

```bash
cd /Users/document/好特卖超级仓/数据分析/JimuReport
mysql -u root -p < db/jimureport.mysql5.7.create.sql
```

按提示输入 MySQL 的 root 密码。

### 3. 修改 JimuReport 里的数据库密码

编辑 `jimureport-example/src/main/resources/application-dev.yml`，找到：

```yaml
spring:
  datasource:
    username: root
    password: ${MYSQL-PASSWORD:}   # 无密码保持空；有密码改为 password: "你的密码"
```

- **本机 root 无密码**：保持 `password: ${MYSQL-PASSWORD:}` 或改为 `password: ""`
- **本机 root 有密码**：改为 `password: "你的密码"`（例如 `password: "root"` 或 `password: "123456"`）

保存后重启 JimuReport：在 `jimureport-example` 目录执行 `mvn spring-boot:run`。

---

## 七、好特卖看板数据准备

安装完成后，执行数据分析项目中的建表脚本，将好特卖数据导入：

```bash
# 在 MySQL 中执行
mysql -u root -p < /path/to/好特卖超级仓/数据分析/scripts/01_create_tables.sql
```
