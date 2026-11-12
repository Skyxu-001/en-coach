<p align="center">
  <img src="docs/images/hero.png" alt="en-coach：在 Claude Code 里顺带学英语" width="100%">
</p>

<p align="center">
  <a href="https://github.com/Skyxu-001/en-coach/actions/workflows/test.yml"><img src="https://github.com/Skyxu-001/en-coach/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-3776ab" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-none-2ea043" alt="零依赖">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">
  <br>
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

# en-coach

**你平时怎么用 Claude Code 就怎么用，每条消息顺带变成一次英语练习。Claude 完全看不到。**

▶️ **两分钟视频介绍：**[B 站（中文）](https://www.bilibili.com/video/BV1gQWm6jEBs) · [YouTube（英文）](https://youtu.be/tpCxBXJ9LZ4)

你发出的每条消息，会被一个又快又便宜的小模型看一眼。大约一秒后，输入框下面出现一两行提示：
英文写错的地方、中文里不会说的那个词的英文、或者"没错，但母语者会这么说"。

<p align="center">
  <img src="docs/images/demo-four-kinds.png" alt="状态栏里的四种提示" width="92%">
  <br><sub>提示内容是 hook 的真实模型输出，终端外框做了简化。</sub>
</p>

## 为什么做这个

我是母语中文的程序员，每天大量时间在跟 Claude Code 说话，一半中文一半英文。
这几个小时本来都可以是英语练习，但什么也没学到；背单词 App 又总坚持不下来。
所以我把练习放到每天本来就在的地方，而且不打扰工作：

- **零额外操作**：不用开 App、不用敲命令、不用背卡片，照常写代码就行。
- **中英夹杂随便写**：写 `how do I 撤销 the last commit`，它就教你 `撤销 → undo / revert / roll back`。想到什么写什么，这是设计意图，不是将就。
- **不影响 Claude**：hook 不往对话里输出任何东西，提示只显示在状态栏，状态栏不会发给模型。装不装它，Claude 的回答都一样（同样的消息两边各跑一遍对照过）。
- **便宜，也不绑定哪一家**：用 DeepSeek，每天约 40 条，一个月大约 **0.1 美元**。OpenAI、Gemini、Claude、通义千问、Kimi、智谱也都实测过，还能跑本地模型（见[测过的模型](#测过的模型)）。

## 教什么

| | 什么时候 | 你会看到 |
|---|---|---|
| **FIX** 纠错 | 写的是英文 | 带上下文的错处和改法：`is failling → is failing` |
| **GAP** 补词 | 中英夹杂 | 你卡住的那部分怎么说：`撤销 → undo / revert / roll back` |
| **SAY** 学表达 | 全是中文 | 只挑一两个值得学的说法：`联调 → integration testing` |
| **REWRITE** ↻ 改写 | 语法没错但像翻译腔 | 母语工程师会怎么说 |

**绿色**是你写的，**红色**是要学的。所有提示同时存进 `~/.claude/english/errors.jsonl`，是你自己的错题本，方便以后复习。

## 安装

需要 Python 3.9+，和一个兼容 OpenAI 接口的模型 API key（默认 DeepSeek，[别家](#测过的模型)也行）。

**装成 Claude Code 插件**（推荐）。在终端里：

```sh
claude plugin install en-coach --marketplace Skyxu-001/en-coach
```

然后在 Claude Code 里跑一次：

```
/en-coach:setup
```

插件自带 hook；`/en-coach:setup` 负责配状态栏，这一步插件自己做不了。插件更新后再跑一次。
Claude Code 低于 2.1.275 的话，先加 marketplace：`claude plugin marketplace add Skyxu-001/en-coach`，
再 `claude plugin install en-coach@en-coach`。

**或者不用插件：**

```sh
git clone https://github.com/Skyxu-001/en-coach.git
cd en-coach
python3 install.py          # Windows 用 py install.py
```

两种方式二选一，别都装。（`/en-coach:setup` 会删掉 `install.py` 装的 hook，所以从手动安装换成插件没问题。）

然后把 key 告诉它，二选一。写进 shell 配置：

```sh
export DEEPSEEK_API_KEY=sk-...
```

或者写进 `~/.claude/settings.json` 的 `env`：

```json
{ "env": { "DEEPSEEK_API_KEY": "sk-..." } }
```

新开一个 Claude Code 会话，随便发一句话试试。两种方式都会：

- 把脚本复制到 `~/.claude/english-coach/`
- 每条消息跑一个**异步**的 `UserPromptSubmit` hook（每次发消息时在后台自动跑的脚本），不会拖慢你的消息
- 让状态栏显示提示；**你原来有状态栏的话会保留**，显示在提示上面
- 改 `settings.json` 之前先备份

`python3 install.py --dry-run` 只显示会改什么，不真改。

卸载：`/en-coach:setup remove`（或 `python3 ~/.claude/english-coach/install.py --uninstall`）把原来的状态栏放回去；用的是插件的话再 `claude plugin uninstall en-coach`。错题本会留着。

没出提示？hook 出错时故意不吭声，所以手动检查一下（插件用户：跑过 `/en-coach:setup` 才有这个文件，提示找不到文件就先跑它）：

```sh
python3 ~/.claude/english-coach/en-coach.py --check     # Windows 用 py
```

它会打印接口地址、模型名、找没找到 key（不打印 key 本身）、模型的原始回复或 HTTP 报错，以及会显示哪些提示。

## 配置

都是可选的环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `EN_COACH_API_KEY` | | 你用的那个接口的 API key |
| `DEEPSEEK_API_KEY` | | 只在接口是 DeepSeek 时才用，免得 DeepSeek 的 key 被发给别家。用别的接口就把它的 key 放进 `EN_COACH_API_KEY` |
| `EN_COACH_BASE_URL` | `https://api.deepseek.com` | 任何兼容 OpenAI 的接口，比如 `https://api.openai.com/v1`、`https://openrouter.ai/api/v1`，或本地 Ollama `http://localhost:11434/v1` |
| `EN_COACH_MODEL` | `deepseek-flash` | 该接口上的模型名 |
| `EN_COACH_EXTRA_BODY` | | 合并进请求的 JSON，用来设各家自己的开关，比如关掉"思考"；值写 `null` 表示删掉这个字段。各家该填什么见下表 |
| `EN_COACH_NATIVE_LANGUAGE` | `zh` | 你的母语：`zh` 中文；**测试版**：`ja` 日语、`ko` 韩语、`es` 西班牙语 |
| `EN_COACH_LOG` | `1` | 设成 `0` 就不记错题本 |
| `EN_COACH_DATA_DIR` | `~/.claude/english`（设了 `CLAUDE_CONFIG_DIR` 就是它下面的 `english`） | 提示和错题本存哪 |

选快的模型：你还盯着刚发的消息时提示就出来，才有用。

### 测过的模型

不一定非用 DeepSeek，换一家只要三行，比如 OpenAI：

```sh
export EN_COACH_BASE_URL=https://api.openai.com/v1
export EN_COACH_MODEL=gpt-4.1-mini
export EN_COACH_API_KEY=sk-...
```

下表每一行都用同样 6 句测试消息（带错的英文、中英夹杂、纯中文）走过真实的 hook，提示都正常。
延迟是模型调用的中位数，2026-11-09 在美国测，每句跑一次：

| 厂商 | `EN_COACH_BASE_URL` | `EN_COACH_MODEL` | `EN_COACH_EXTRA_BODY` | 中位延迟 |
|---|---|---|---|---|
| DeepSeek（默认） | `https://api.deepseek.com` | `deepseek-flash` | | 1.2 秒 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` | | 1.1 秒 |
| OpenAI | `https://api.openai.com/v1` | `gpt-5.4-mini` | `{"max_tokens": null, "max_completion_tokens": 320, "reasoning_effort": "none"}` | 0.8 秒 |
| Gemini（经 OpenRouter） | `https://openrouter.ai/api/v1` | `google/gemini-3.8-flash` | `{"reasoning": {"effort": "low"}}` | 1.9 秒 |
| Gemini（经 OpenRouter） | `https://openrouter.ai/api/v1` | `google/gemini-3.5-flash-lite` | | 0.9 秒 |
| Claude（经 OpenRouter） | `https://openrouter.ai/api/v1` | `anthropic/claude-haiku-5.5` | `{"reasoning": {"effort": "none"}}` | 1.0 秒 |
| 通义千问（阿里云国际站） | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `qwen3.8-flash` | `{"enable_thinking": false}` | 1.7 秒 |
| Kimi（月之暗面） | `https://api.moonshot.cn/v1` | `kimi-k2.6` | `{"temperature": null, "thinking": {"type": "disabled"}}` | 2.8 秒 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.3-flashx` | `{"reasoning_effort": "low"}` | 2.6 秒 |

说明：

- 指令是在 DeepSeek 上调的，它也仍然最便宜。Gemini 3.8 Flash 给的提示最多；Claude Haiku 有一句英文的错没挑出来。
- Kimi、智谱、通义是从美国测的，在国内用应该更快。platform.moonshot.cn 申请的 Kimi key 只能用 `api.moonshot.cn`。
- `EN_COACH_EXTRA_BODY` 是"字符串里的 JSON"。在 shell 里用单引号包起来：
  `export EN_COACH_EXTRA_BODY='{"reasoning_effort": "low"}'`；写进 `settings.json` 的 `env` 时，里面的双引号要转义：
  `"EN_COACH_EXTRA_BODY": "{\"reasoning_effort\": \"low\"}"`。

**表里没有的模型？** 失败几乎都是两种原因之一：模型先"思考"再回答，把 token 全花在思考上（回复为空）；或者它不认某个标准字段（`max_tokens`、`temperature`）。
跑一下 `--check` 看是哪种，再用 `EN_COACH_EXTRA_BODY` 关掉思考或删掉那个字段。别用只会推理的模型：实测一个花了 7.8 秒，一条都没出。

**本地模型（Ollama）** 也能用：`EN_COACH_BASE_URL=http://localhost:11434/v1`，模型名随意，`EN_COACH_API_KEY` 随便填个非空值。效果看模型大小：
小模型（1B 到 3B，4 GB 显卡能跑的那种）几乎给不出能用的提示，7B 到 27B 的开源模型也明显不如上表的云端模型。
用你的机器能在 12 秒限时内轻松跑完的最大模型；另外 Ollama 刚加载模型后的第一条会慢一些。

## 原理和踩过的坑

工作流程图、每个设计取舍、以及一长串"不报错、只是悄悄变差"的坑（大多有对应测试），
见英文 README 的 *How it works* 和 [docs/lessons-learned.md](docs/lessons-learned.md)。
其中包括：我试了七种办法想让模型多教几条，全部无效。

## 常见问题

**会影响 Claude 的回答吗？** 不会。hook 不往标准输出写任何东西，状态栏也不会发给模型。

**会把什么发给 API？** 你这条消息里的文字部分，最多 400 个字符。``` 围起来的代码块、看着像代码、日志、命令或报错堆栈的行会先被过滤掉；过滤是逐行判断、尽力而为，写得像句子的代码行仍可能混进去。别的都不发：不发你的文件，也不发 Claude 的回答。看起来像密钥的内容在发送和写错题本之前都会打码：常见格式的 API key 和 token、`Authorization: Basic / Bearer / Token ...`、`password is ...`、网址里的 `用户:密码@`、`API_KEY=...`、`dbPassword: ...`、`PGPASSWORD=...` 这类赋值（值里要有数字，或者长度到 16 个字符）、`curl -u` 和 `mysql -p` 里的密码、私钥、`密码是 ...`。这同样只是尽力而为，不是保证。已知漏掉的：UUID 形状的 key、64 位十六进制密钥、较短的 base64 密钥、只有字母或带空格的密码、网址里含 `/` 的密码、cookie。别往 prompt 里贴密钥。

**慢吗？** hook 在后台跑。按回车后 1 到 6 秒出提示：模型约 1 秒，状态栏最多再等 5 秒刷新。别把 `refreshInterval` 调到 5 以下，原因见 lessons 文档。

## 测试

```sh
python3 -B tests/test_en_coach.py
```

纯离线，不需要 key。CI 在 Linux、macOS、Windows 上用 Python 3.9 和 3.13 跑。

## 致谢

"异步 hook + 状态栏显示"的做法来自 [rapita/claude-grammar](https://github.com/rapita/claude-grammar)，
"读对话记录判断是不是真人输入"的思路来自 [zhangrui-vibe/claude-code-english-coach](https://github.com/zhangrui-vibe/claude-code-english-coach)。
两者都是 MIT 许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

[MIT](LICENSE)

---

如果觉得这个项目有用或有意思，欢迎点个 ⭐，让更多人看到它。谢谢！
