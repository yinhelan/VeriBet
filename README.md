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
  reviews/
    review_template.json
  patches/
    .gitkeep
  scripts/
    veribet_runner.py
    veribet_eval.py
    veribet_live.py
    veribet_live_batch.py
    veribet_api.py
    veribet_postmortem.py
    veribet_rule_proposer.py
    veribet_patch_test.py
    veribet_patch_apply.py
    run_targeted.sh
    run_veribet.sh
    run_veribet_resilient.sh
    run_live.sh
    run_live_batch.sh
    run_api.sh
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

## API 自动化

启动本地 API：

```bash
scripts/run_api.sh
```

默认监听：

```text
http://127.0.0.1:8012
```

### 健康检查

```bash
curl http://127.0.0.1:8012/healthz
```

### 单场分析

```bash
curl -X POST http://127.0.0.1:8012/api/live/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "input": {
      "basic_info": {
        "competition": "English Premier League",
        "match": "Brighton vs Newcastle"
      },
      "snapshots": {},
      "notes": {
        "stage": "pre_match"
      }
    },
    "retries": 2,
    "output_path": "live_outputs/api_example.result.json"
  }'
```

### 批量分析

按目录批量跑：

```bash
curl -X POST http://127.0.0.1:8012/api/live/batch \
  -H 'Content-Type: application/json' \
  -d '{
    "inputs_path": "inputs",
    "output_dir": "live_outputs_api_batch",
    "retries": 2
  }'
```

也可以直接传数组：

```bash
curl -X POST http://127.0.0.1:8012/api/live/batch \
  -H 'Content-Type: application/json' \
  -d '{
    "inputs": [
      {
        "name": "match_a",
        "input": {
          "basic_info": {
            "competition": "Test League",
            "match": "A vs B"
          },
          "snapshots": {},
          "notes": {
            "stage": "pre_match"
          }
        }
      }
    ]
  }'
```

### 生成赛后复盘

```bash
curl -X POST http://127.0.0.1:8012/api/reviews/postmortem \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "inputs/example_match.json",
    "result_path": "live_outputs/example_single.result.json",
    "ft_score": "2-2",
    "ht_score": "0-0",
    "tags": ["主热未封口", "平局低估"],
    "judgement": "主热承接过重但封口不足，平局兑现。",
    "rule_delta": "联赛主热2.20~2.35且平局被显著压冷时，提高平局防守权重。",
    "analyst": "yinhelan",
    "output_path": "reviews/example_match.review.json"
  }'
```

### 生成候选补丁

```bash
curl -X POST http://127.0.0.1:8012/api/patches/propose \
  -H 'Content-Type: application/json' \
  -d '{
    "review_path": "reviews/example_match.review.json",
    "output_path": "patches/example_match.candidate.json"
  }'
```

### 跑补丁验证

```bash
curl -X POST http://127.0.0.1:8012/api/patches/test \
  -H 'Content-Type: application/json' \
  -d '{
    "patch_paths": ["patches/example_match.candidate.json"],
    "output_dir": "patch_test_runs/api_example"
  }'
```

### 应用通过验证的补丁

```bash
curl -X POST http://127.0.0.1:8012/api/patches/apply \
  -H 'Content-Type: application/json' \
  -d '{
    "summary_path": "patch_test_runs/api_example/summary.json"
  }'
```

### 单接口串联：分析 + 复盘 + 候选补丁

如果你赛后想一条请求直接完成整条链路：

```bash
curl -X POST http://127.0.0.1:8012/api/ingest-and-review \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "inputs/example_match.json",
    "ft_score": "2-2",
    "ht_score": "0-0",
    "tags": ["主热未封口", "平局低估"],
    "judgement": "主热承接过重但封口不足，平局兑现。",
    "rule_delta": "联赛主热2.20~2.35且平局被显著压冷时，提高平局防守权重。",
    "analyst": "yinhelan",
    "result_output_path": "live_outputs/api_ingest.result.json",
    "review_output_path": "reviews/api_ingest.review.json",
    "patch_output_path": "patches/api_ingest.candidate.json"
  }'
```

这个接口会：
- 如未提供 `result` / `result_path`，先跑 live analyze
- 自动生成 review
- 自动生成 candidate patch

### 单接口串联到补丁验证

如果你想一条请求直接跑到 `summary.json`：

```bash
curl -X POST http://127.0.0.1:8012/api/ingest-review-and-test \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "inputs/example_match.json",
    "ft_score": "2-2",
    "ht_score": "0-0",
    "tags": ["主热未封口", "平局低估"],
    "judgement": "主热承接过重但封口不足，平局兑现。",
    "rule_delta": "联赛主热2.20~2.35且平局被显著压冷时，提高平局防守权重。",
    "analyst": "yinhelan",
    "result_output_path": "live_outputs/api_ingest_test.result.json",
    "review_output_path": "reviews/api_ingest_test.review.json",
    "patch_output_path": "patches/api_ingest_test.candidate.json",
    "patch_test_output_dir": "patch_test_runs/api_ingest_test",
    "patch_test_retries": 1,
    "retries": 0
  }'
```

这个接口会：
- 先分析
- 再复盘
- 再产 candidate patch
- 最后直接跑 `patch_test`

### 异步任务模式

如果你不想让 HTTP 连接一直等着回归结束，用异步任务接口：

提交任务：

```bash
curl -X POST http://127.0.0.1:8012/api/jobs/ingest-review-and-test \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "inputs/example_match.json",
    "ft_score": "2-2",
    "ht_score": "0-0",
    "tags": ["主热未封口", "平局低估"],
    "judgement": "主热承接过重但封口不足，平局兑现。",
    "rule_delta": "联赛主热2.20~2.35且平局被显著压冷时，提高平局防守权重。",
    "analyst": "yinhelan",
    "result_output_path": "live_outputs/api_job.result.json",
    "review_output_path": "reviews/api_job.review.json",
    "patch_output_path": "patches/api_job.candidate.json",
    "patch_test_output_dir": "patch_test_runs/api_job",
    "patch_test_retries": 1
  }'
```

会先返回：

```json
{
  "ok": true,
  "job_id": "ingest_review_and_test_...",
  "status": "queued"
}
```

查状态：

```bash
curl http://127.0.0.1:8012/api/jobs/<job_id>
```

状态会依次变成：
- `queued`
- `running`
- `completed`
- `failed`

## 复盘归因

标准复盘模板：

```bash
reviews/review_template.json
```

生成一份赛后复盘：

```bash
.venv/bin/python scripts/veribet_postmortem.py \
  --input inputs/example_match.json \
  --result live_outputs/example.result.json \
  --output reviews/example_match.review.json \
  --ft-score 2-2 \
  --ht-score 0-0 \
  --tag 主热未封口 \
  --tag 平局低估 \
  --judgement "主热承接过重但封口不足，平局兑现。" \
  --rule-delta "联赛主热2.20~2.35且平局被显著压冷时，提高平局防守权重。" \
  --analyst yinhelan
```

这个 review 会自动写入：
- 实际赛果
- 主/次/尾方向是否命中
- 当时的 VeriBet 结构、风险、方向、flags
- 你的人工复盘标签与建议修正规则

## 候选规则补丁

根据复盘自动生成候选规则补丁：

```bash
.venv/bin/python scripts/veribet_rule_proposer.py \
  --reviews reviews \
  --output-dir patches
```

输出是结构化 candidate JSON，不会直接改 prompt。

示例字段：

```json
{
  "rule_id": "league_home_heat_draw_guard_v1",
  "target_section": "rulebook",
  "change_type": "append_rule",
  "content": "候选规则文本",
  "rationale": {
    "match_id": "...",
    "postmortem_tags": ["..."]
  },
  "status": "candidate"
}
```

这一步的目标是：
- 从 review 抽出稳定的错因模式
- 生成候选修正规则
- 但不自动写入主 bundle

## 候选补丁验证

把 candidate patch 临时并入 bundle，跑基线与补丁版回归对比：

```bash
.venv/bin/python scripts/veribet_patch_test.py \
  --bundle prompts/veribet_prompt_bundle_v412_candidate.yaml \
  --pack packs/veribet_regression_pack_v1.yaml \
  --patch patches/2026-04-29_efl_southampton_vs_ipswich.review.candidate.json \
  --output-dir patch_test_runs/efl_draw_guard
```

输出：
- `patch_test_runs/.../baseline/`
- `patch_test_runs/.../patched/`
- `patch_test_runs/.../summary.json`

`summary.json` 里会包含：
- baseline 总分
- patched 总分
- improved cases
- regressed cases
- 自动建议：`accept / review / reject`

这一步仍然不会自动改主 bundle。

## 候选补丁写回

只有当 `patch_test` 的 `summary.json` 里 `decision = accept` 时，才建议写回主 bundle：

```bash
.venv/bin/python scripts/veribet_patch_apply.py \
  --summary patch_test_runs/efl_draw_guard/summary.json
```

行为：
- 自动检查 `decision`
- 自动备份原 bundle
- 只把新的 patch marker 追加写入 `rulebook`
- 若 `decision != accept`，默认拒绝写回

如果你只是临时强制测试写回逻辑：

```bash
.venv/bin/python scripts/veribet_patch_apply.py \
  --summary patch_test_runs/efl_draw_guard/summary.json \
  --force
```

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
- 复盘归因脚本可生成标准 review JSON
- `VB-009` 风险等级修正已生效
