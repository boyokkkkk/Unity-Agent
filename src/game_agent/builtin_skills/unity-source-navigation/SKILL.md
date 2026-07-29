---
name: unity-source-navigation
description: Locate and verify gameplay system source files in a Unity project without traversing generated content.
triggers:
  - unity
  - source
  - script
  - locate
  - find
  - assets
  - 源码
  - 定位
  - 查找
---
# Unity source navigation

- Scope recursive discovery to `Assets` first. Search `Packages` only when package code is relevant.
- Never recursively inspect `Library`, `Temp`, `Logs`, `obj`, `.git`, `Build`, `Builds`, or `UserSettings`.
- Use Windows PowerShell syntax. Prefer `Get-ChildItem Assets -Recurse -Filter *.cs` and `Select-String`.
- Narrow candidates by directory and type name, then read only the small set of files needed to verify declarations and responsibilities.
- Finish by calling `submit` with paths, responsibilities, and important relationships.
