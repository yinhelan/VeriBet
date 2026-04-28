# VeriBet Local Repository

本仓库是已经可在本机直接运行的 `VeriBet v4.12` 版本。

当前特性：
- 使用本机 Python 虚拟环境
- 通过 `OmniRoute` 走 OpenAI-compatible 接口
- 回归测试支持失败 case 自动补跑
- live 推理支持单场与批量模式
- 已处理 HTTPS 证书链
- 已处理瞬时网络错误自动重试

## 目录结构

```text
veribet/
  README.md
  .env.example
  .gitignore
  requirements.txt
  Makefile
  prompts/
    veribet_prompt_bundle_v412_candidate.yaml
  packs/
    veribet_regression_pack_v1.yaml
  scripts/
    veribet_runner.py
    veribet_eval.py
    veribet_live.py
    veribet_live_batch.py
    run_targeted.sh
    run_veribet.sh
    run_veribet_resilient.sh
    run_live.sh
    run_live_batch.sh
  inputs/
    live_match_input.json
    example_match.json
  outputs/
```

## 环境准备

第一次使用：

```bash
cd /Users/bluegalaxy/codex-bin/veribet
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

然后编辑 `.env`：

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://sub.yinhelao.com:8444/v1
OPENAI_MODEL=codex/gpt-5.4
```

## 回归测试

### 跑目标 case

```bash
cd /Users/bluegalaxy/codex-bin/veribet
scripts/run_targeted.sh
```

输出：
- `outputs/veribet_targeted_outputs.yaml`
- `outputs/veribet_targeted_report.json`

### 跑完整回归

```bash
scripts/run_veribet.sh
```

输出：
- `outputs/veribet_full_outputs.yaml`
- `outputs/veribet_full_report.json`

### 跑自动补跑版完整回归

```bash
scripts/run_veribet_resilient.sh
```

逻辑：
- 先跑一轮完整回归
- 找出失败 case
- 对失败 case 最多重试 3 次
- 合并补跑成功结果
- 输出最终 merged 报告

重点看：
- `outputs/veribet_full_outputs_merged.yaml`
- `outputs/veribet_full_report_merged.json`

## Live 推理

### 单场

```bash
scripts/run_live.sh inputs/example_match.json live_outputs/example.result.json
```

默认输入也可以直接用：

```bash
scripts/run_live.sh
```

默认会读取：
- `inputs/live_match_input.json`

### 批量

```bash
scripts/run_live_batch.sh inputs live_outputs_batch
```

这会读取 `inputs/` 下所有 `*.json`，每个输入生成一个 `.result.json`。

## Live 自动重试

单场和批量都支持通过环境变量控制自动重试：

```bash
VERIBET_LIVE_RETRIES=3 VERIBET_LIVE_RETRY_DELAY=2 scripts/run_live.sh inputs/example_match.json live_outputs/example.result.json
```

```bash
VERIBET_LIVE_RETRIES=3 VERIBET_LIVE_RETRY_DELAY=2 scripts/run_live_batch.sh inputs live_outputs_batch
```

默认：
- `VERIBET_LIVE_RETRIES=2`
- `VERIBET_LIVE_RETRY_DELAY=2`

## Prompt 调试

### 回归样本 prompt

```bash
.venv/bin/python scripts/veribet_runner.py \
  --pack packs/veribet_regression_pack_v1.yaml \
  --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
  --case-id VB-009 \
  --print-sample-prompt
```

### live prompt

```bash
.venv/bin/python scripts/veribet_live.py \
  --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
  --input inputs/live_match_input.json \
  --debug-prompt
```

## Makefile

常用快捷命令：

```bash
make setup
make targeted
make full
make resilient
make live
make batch
```

## GitHub 推送前

已忽略：
- `.env`
- `.venv/`
- `outputs/`
- `live_outputs/`
- `live_outputs_batch/`
- `__pycache__/`

建议推送前先看：

```bash
git status
```

如果你要新建仓库并推送：

```bash
git init
git add .
git commit -m "Initial VeriBet local repo"
git branch -M main
git remote add origin <你的GitHub仓库地址>
git push -u origin main
```

## 当前已验证

- 回归 runner 可跑
- 自动补跑版 merged 报告可收敛到 `160/160`
- live 单场可跑
- live 批量可跑
- `VB-009` 风险等级修正已生效

