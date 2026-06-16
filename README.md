# 大数据分析课程实验仓库

本仓库用于保存《大数据分析》课程实验交付物。为避免不同实验的代码、报告和输出文件混在仓库根目录，当前已按实验编号整理为独立目录。

## 目录说明

```text
.
├─ test4/
│  ├─ README.md
│  ├─ run_m1_pipeline.py
│  ├─ benchmark.py
│  ├─ m1_tester.py
│  ├─ M1_实验报告.md
│  ├─ requirements.txt
│  └─ output/
└─ test14/
   ├─ README.md
   ├─ run_app.py
   ├─ validate_system.py
   ├─ dashboard/
   ├─ images/
   ├─ output/
   └─ 实验十四_M4系统联调与工程规范实验报告.md
```

## 实验入口

- `test4/`：Milestone 1 数据清洗与本地处理实验，包含 M1 数据管道、测试脚本、实验报告和输出图表。
- `test14/`：Milestone 4 系统联调与工程规范实验，包含一键启动脚本、FastAPI + ECharts 看板、系统降级接口、README、`.gitignore` 和实验报告。

## 注意事项

- 大体积数据、数据库文件、虚拟环境和缓存文件不应提交到仓库。
- 每个实验目录内部保留自己的 README 和运行说明。
- 新增实验时建议继续按 `testN/` 目录组织，避免将实验文件直接放在仓库根目录。
