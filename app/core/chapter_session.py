# -*- coding: utf-8 -*-
"""章会话消息栈：一章一个会话，阶段=追加轮次（DeepSeek 前缀缓存友好）

旧架构里每个阶段都是独立单轮请求（prompt 全量重发），前缀无法命中缓存。
本类把一章变成一个会话：

- system 固定为双层稳定前缀（project_header + chapter_header），构造时传入；
- 正文经 ask() 以 user→assistant 一轮进入历史，后续审校/追踪/摘要阶段作为
  追加 user 轮依次推进——历史前缀逐字节复用，DeepSeek 前缀缓存得以命中；
- 并发投票等场景：snapshot() 取当前栈深拷贝并行请求（各自 snapshot+[user]），
  结束后由调用方用 commit_turn() 把「首个完成的投票」固化为正式轮次；
- disabled（配置关闭 / 客户端不支持 chat_turn）时 enabled=False，调用方
  回退既有单轮 chat_stream 路径。

本类只管消息栈结构与固化时机：重试/退避/输出清洗等语义留在 LLM 客户端与
调用方既有流程里，不在此重复实现。
"""
import copy


class ChapterSession:
    """章会话消息栈：一章一个会话，阶段=追加轮次。

    - system 固定为双层稳定前缀（project_header + chapter_header），构造时传入
    - ask() 追加 user 轮、调用客户端、把回复固化为 assistant 轮
    - 并发投票等场景：snapshot() 取当前栈深拷贝，并行请求各自 snapshot+[user]，
      结束后用 commit_turn() 把「首个完成的投票」追加为正式轮次
    - disabled（配置关闭/客户端不支持）时 enabled=False，调用方回退单轮 chat_stream
    """

    # 阶段 user 轮的统一作用域声明：多轮历史里此前的评审发言只作素材不作结论，
    # 由调用方拼在阶段 user_text 前，防止上一阶段的判断污染本阶段输出。
    SCOPE_LINE = ("（作用域：仅依据系统设定基准与本会话中的章正文消息执行本步；"
                  "此前轮次的评审/结论性发言不得影响本步输出。）")

    def __init__(self, client, system_text: str, enabled: bool = True):
        self._client = client
        self._system_text = system_text or ""
        # 配置关闭或客户端没有 chat_turn（旧测试替身/壳客户端）都视为不可用：
        # 调用方据 enabled 回退单轮 chat_stream，而不是中途撞 AttributeError。
        self._enabled = bool(enabled) and callable(getattr(client, "chat_turn", None))
        self._messages = [{"role": "system", "content": self._system_text}]
        self._pending_prose = None   # restart_with_prose 的种子：只影响下一次 ask
        self._turns = 0              # 已固化的（user,assistant）轮次数

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def system_text(self) -> str:
        return self._system_text

    def ask(self, user_text: str, *, on_chunk=None, on_reasoning=None,
            phase: str = "", temperature=None, abort=None,
            client=None, postprocess=None) -> str:
        """追加 user 轮并同步等待回复；回复固化为 assistant 轮后返回原文。

        前置条件：enabled 为真（否则 RuntimeError，调用方应回退单轮 chat_stream）。
        client：本轮使用的客户端覆盖（各阶段槽位路由不同模型时传对应槽的
        client；不传用构造时的默认 client）。历史前缀的缓存复用只在同一
        模型间生效，但多轮结构在任何路由下语义都成立。
        postprocess：回复后处理（如 clean_llm_output），处理后的文本作为
        assistant 轮固化并返回——历史中的「章正文」与调用方看到的逐字节一致。
        异常安全：chat_turn 失败时不把该轮固化进栈，栈保持调用前状态
        （restart_with_prose 的种子同样保留——重试的 ask 仍带正文前缀），
        由上层按既有重试语义处理。
        """
        if not self._enabled:
            raise RuntimeError("ChapterSession 未启用（配置关闭或客户端不支持多轮）："
                               "调用方应回退单轮 chat_stream")
        content = user_text
        if self._pending_prose is not None:
            # 断点续跑：正文作为种子拼进首个 user 轮（仅一次，之后靠历史），
            # 避免连续两条 user 消息的非法结构。
            content = f"## 本章正文\n{self._pending_prose}\n\n{user_text}"
        reply = (client or self._client).chat_turn(
            self._messages + [{"role": "user", "content": content}],
            on_chunk=on_chunk, on_reasoning=on_reasoning, phase=phase,
            temperature=temperature, abort=abort)
        if postprocess:
            reply = postprocess(reply)
        # 成功才固化：失败让上层按既有重试语义处理
        self._messages.append({"role": "user", "content": content})
        self._messages.append({"role": "assistant", "content": reply})
        self._pending_prose = None
        self._turns += 1
        return reply

    def snapshot(self) -> list:
        """返回当前 messages 的深拷贝（并发请求各自携带，互不污染）。"""
        return copy.deepcopy(self._messages)

    def commit_turn(self, user_text: str, assistant_text: str) -> None:
        """把一轮（user+assistant）追加进正式栈；并发投票后由调用方调用恰好一次。"""
        self._messages.append({"role": "user", "content": user_text})
        self._messages.append({"role": "assistant", "content": assistant_text})
        self._turns += 1

    def rollback_to(self, turn_count_before: int) -> None:
        """截断回栈到「第 N 轮固化后」的状态（闸门回退/修复稿被否决时使用）。

        历史里的去味稿/修复稿若被调用方否决（正文还原为旧版），栈里留着的
        「最近一条章正文消息」就会指向已废弃文本——后续阶段按历史引用会审错
        对象。截断同时清除这些轮次，使历史与实际正文重新一致。
        种子（pending_prose）不受影响。
        """
        if not (0 <= turn_count_before <= self._turns):
            raise ValueError(f"rollback_to: 目标轮数 {turn_count_before} 超出当前范围（0~{self._turns}）")
        drop = (self._turns - turn_count_before) * 2
        if drop:
            del self._messages[-drop:]
        self._turns = turn_count_before

    def restart_with_prose(self, prose: str) -> None:
        """断点续跑：重置栈为 [system]，并把 prose 记为种子；
        下一次 ask() 的 user_text 前自动拼上「## 本章正文\n{prose}\n\n」
        （仅拼一次，之后靠历史），避免连续两条 user 消息的非法结构。"""
        self._messages = [{"role": "system", "content": self._system_text}]
        self._pending_prose = prose
        self._turns = 0

    def turn_count(self) -> int:
        """已固化的（user,assistant）轮次数。"""
        return self._turns
