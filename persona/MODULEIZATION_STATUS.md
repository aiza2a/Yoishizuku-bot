# persona 模块化状态

- `modules/`：唯一的人设正文源文件，按文件名字典序拼接。
- `systemprompt.md`：由模块构建出的生产文件，不再手工直接修改。
- `build_persona_prompt.py`：按原始字节拼接，保证构建前后逐字节一致。
- `systemprompt.working_draft.md`：历史工作副本，不参与生产构建。

当前模块已与生产 `systemprompt.md` 完成字节级一致性验证。
