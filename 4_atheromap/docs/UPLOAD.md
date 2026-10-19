# 把模块放进团队 GitHub 仓库

这个压缩包用于提交源码。解压后得到 `atheromap/` 文件夹；在团队仓库中应放到 **`bioagent/agents/atheromap/`**，与现有 `agents/popgen/` 并列。

不要把 ZIP 当作模块直接上传，也不要把整个服务器项目目录或大矩阵加入 Git。

## 这次需要上传

整个整理后的 `atheromap/`，包括源码、README、config 示例、只读检查工具和 docs。包内没有原始矩阵、环境压缩包、实际结果数据或访问凭证。

以后补交最终 marker、`.gs`、方法配置、小型汇总表和代表图时，再确认来源、版本以及是否允许分享。大数据记录获取方式 / 存储位置即可。

## 在自己的仓库副本中操作

以下命令需在有 Git 且已配置个人 GitHub 登录的电脑或服务器执行。本说明不会索要 token 或密码。

1. 若还没有克隆仓库，进入一个用于放代码的目录后执行：

   ```bash
   git clone https://github.com/sunming-code/bioagent.git
   cd bioagent
   ```

   如果已有仓库，进入那个 `bioagent` 目录即可，不要重复克隆覆盖。

2. 查看是否有未提交改动；如有，先保留并弄清它们属于谁：

   ```bash
   git status
   ```

3. 在工作目录干净时，基于团队主分支建立本次分支：

   ```bash
   git switch main
   git pull --ff-only
   git switch -c feature/atheromap-carotid
   ```

   如果同名分支已存在，先确认是不是自己的上次工作；不要强制覆盖它。

4. 用文件管理器或 `cp -a` 把解压后的 `atheromap/` 放到仓库 `agents/`。如果已经有 `agents/atheromap/`，先比较差异，不要直接整目录覆盖。命令示例（将占位路径改成真实解压目录）：

   ```bash
   cp -a /实际解压位置/atheromap agents/
   git status --short
   ```

5. 仅暂存这个模块，查看实际提交范围：

   ```bash
   git add agents/atheromap
   git diff --cached --stat
   git diff --cached --check
   ```

   预期全部文件都在 `agents/atheromap/` 下，没有原始矩阵、私钥或 Conda 环境压缩包。如果出现其他大文件，先停止并检查；不要用 `git add .` 把无关东西一起加进去。

6. 检查无误后提交并推送自己的分支：

   ```bash
   git commit -m "Add AtheroMap carotid scDRS and gsMap analysis scripts"
   git push -u origin feature/atheromap-carotid
   ```

7. 在 GitHub 上为这个分支创建 Pull Request，目标是 `main`，让队友检查后合并。没有团队仓库写权限时，请维护者添加协作者，或 fork 后向团队仓库提 PR；无需借用队友账号。

## 可用的 PR 描述

> 整理颈动脉斑块 scDRS（GSE159677）与 gsMap（GSE241346）分析脚本，新增工作目录配置、输入检查、运行说明、来源清单及已知缺口记录。保留原分析函数和参数；将机器专属路径改为显式配置，并将 gsMap review 输出移到工作目录。完成静态语法及路径接口检查；未用真实数据重新运行，环境版本、标注表、基因集及部分上游转换步骤仍需补齐。本 PR 暂未实现 Agent 工具接口。

本包没有替你登录 GitHub、创建远程分支或完成上传。推送结果以你实际终端和 GitHub 页面为准。
