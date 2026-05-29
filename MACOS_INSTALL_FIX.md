# vnpy_ctp macOS 安装修复说明

## 背景

在 macOS 上执行：

```bash
pip install .
```

安装 `vnpy_ctp` 时，构建阶段失败，主要报错包括：

```text
unknown type name 'CThostFtdcInvestorInfoCommRecField'
unknown type name 'CThostFtdcCombLegField'
unknown type name 'CThostFtdcInputOffsetSettingField'
no member named 'LoginDRIdentityID'
no member named 'OptionValue'
too many arguments to function call
ld: library 'thostmduserapi_se' not found
```

这些错误不是 pip 本身导致的，而是源码、CTP SDK 头文件、CTP 动态库之间版本不一致导致的。

## 根本原因

当前项目版本是：

```text
vnpy_ctp 6.7.11.4
```

但仓库中 bundled 的 macOS CTP framework 实际是较旧的 CTP SDK：

```text
v6.7.7_MacOS_20240716
```

当前 C++ 绑定源码引用了 CTP 6.7.11 中新增的类型、字段和函数，但 macOS 目录下的旧版 CTP 6.7.7 头文件和 framework 不包含这些内容，因此编译失败。

另外，`meson.build` 的 macOS 链接配置也存在问题：虽然 macOS 分支声明了 framework 依赖，但真正构建 Python 扩展模块时仍然使用：

```text
-L vnpy_ctp/api/libs -lthostmduserapi_se
-L vnpy_ctp/api/libs -lthosttraderapi_se
```

而 `vnpy_ctp/api/libs` 目录里是 Windows `.lib` 文件，macOS 下应该链接：

```text
vnpy_ctp/api/thostmduserapi_se.framework
vnpy_ctp/api/thosttraderapi_se.framework
```

所以在 C++ 编译问题修复后，还会继续遇到 `ld: library 'thostmduserapi_se' not found` 链接错误。

## 修改文件

本次修复修改了以下 4 个文件：

```text
meson.build
vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp
vnpy_ctp/api/vnctp/vnctptd/vnctptd.cpp
vnpy_ctp/api/vnctp/vnctptd/vnctptd.h
```

## 修改内容

### 1. 修复 macOS 下的 framework 链接

文件：

```text
meson.build
```

调整 macOS 构建逻辑，让 `vnctpmd` 和 `vnctptd` 扩展模块真正使用 bundled framework：

```text
vnpy_ctp/api/thostmduserapi_se.framework
vnpy_ctp/api/thosttraderapi_se.framework
```

Linux 和 Windows 的原有链接方式保持不变。

### 2. 修复行情接口 MD 的旧 SDK 兼容

文件：

```text
vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp
```

macOS 旧版 CTP SDK 中，`CThostFtdcRspUserLoginField` 不包含以下字段：

```text
LoginDRIdentityID
UserDRIdentityID
LastLoginTime
ReserveInfo
```

因此在 macOS 下跳过这些字段映射。

同时，macOS bundled SDK 的 `CreateFtdcMdApi` 只支持 3 参数版本：

```cpp
CreateFtdcMdApi(pszFlowPath.c_str(), false, false)
```

而不是新版源码中的 4 参数版本。

### 3. 修复交易接口 TD 的旧 SDK 兼容

文件：

```text
vnpy_ctp/api/vnctp/vnctptd/vnctptd.cpp
vnpy_ctp/api/vnctp/vnctptd/vnctptd.h
```

macOS 旧版 CTP SDK 缺少部分 6.7.11 新增的结构体和回调，例如：

```text
CThostFtdcInvestorInfoCommRecField
CThostFtdcCombLegField
CThostFtdcInputOffsetSettingField
CThostFtdcOffsetSettingField
CThostFtdcCancelOffsetSettingField
```

对应的 C++ SPI 回调和 task process 函数在 macOS 下使用 `#ifndef __APPLE__` 屏蔽。

macOS 旧版 CTP SDK 也缺少部分字段，例如：

```text
OptionValue
LoginDRIdentityID
UserDRIdentityID
LastLoginTime
ReserveInfo
```

这些字段在 macOS 下跳过映射。

旧版 SDK 不支持的主动请求函数在 macOS 下直接返回 `-1`，例如：

```text
reqQryInvestorInfoCommRec
reqQryCombLeg
reqOffsetSetting
reqCancelOffsetSetting
reqQryOffsetSetting
reqQryUserSession
registerWechatUserSystemInfo
submitWechatUserSystemInfo
```

这样可以保证扩展模块能够编译和导入，同时明确表示这些旧 SDK 不支持的接口调用失败。

## 验证结果

使用以下命令验证构建：

```bash
/venv/bin/python -m pip wheel . -w /private/tmp/vnpy_ctp_wheel_test -Csetup-args=-Dwarning_level=0
```

构建成功，生成 wheel：

```text
/private/tmp/vnpy_ctp_wheel_test/vnpy_ctp-6.7.11.4-cp310-cp310-macosx_13_0_x86_64.whl
```

并验证 Python 导入成功：

```python
from vnpy_ctp.api import MdApi, TdApi
```

## 在其他电脑安装

### 方式一：使用修改后的源码安装

推荐方式。把当前修复后的仓库同步到目标电脑，然后执行：

```bash
cd vnpy_ctp
python -m pip install .
```

这种方式适合不同 Python 小版本或不同 macOS 环境。

### 方式二：直接安装已构建 wheel

如果目标电脑环境一致，可以直接安装构建好的 wheel。

适用条件：

```text
macOS
x86_64
Python 3.10
```

安装命令：

```bash
python -m pip install /private/tmp/vnpy_ctp_wheel_test/vnpy_ctp-6.7.11.4-cp310-cp310-macosx_13_0_x86_64.whl
```

如果目标电脑是 Apple Silicon，或者 Python 版本不是 3.10，不建议直接复用这个 wheel，应该使用修改后的源码重新构建安装。

## 注意事项

这次修复的目标是让当前源码能够兼容仓库 bundled 的 macOS CTP 6.7.7 framework，并成功完成安装。

由于 macOS framework 本身仍然是旧版 CTP SDK，所以 6.7.11 中新增、但 6.7.7 不存在的接口在 macOS 下不会真正可用。相关主动请求函数会返回 `-1`。

如果未来替换为真正的 CTP 6.7.11 macOS SDK framework 和对应头文件，可以再移除这些 macOS 兼容屏蔽逻辑，恢复完整 6.7.11 接口。
