"""本地队列与消息去重表。"""
from __future__ import annotations

from collector.spool import Spool


def test_enqueue_then_pending_roundtrip(tmp_path):
    spool = Spool(tmp_path)
    entry = spool.enqueue(key="sess-000001", envelope={"modality": "audio"}, media=b"RIFFfake")

    pending = spool.pending()
    assert [e.key for e in pending] == [entry.key]
    assert pending[0].envelope() == {"modality": "audio"}
    assert pending[0].media() == b"RIFFfake"
    assert spool.depth() == 1

    spool.discard(pending[0])
    assert spool.pending() == []
    assert spool.depth() == 0


def test_pending_is_oldest_first(tmp_path):
    """录音的先后顺序对时间线有意义，补传不能乱序。"""
    spool = Spool(tmp_path)
    for index in range(3):
        entry = spool.enqueue(key=f"sess-{index:06d}", envelope={"n": index}, media=b"x")
        # 落盘时间戳的分辨率可能不够，显式拉开
        import os

        os.utime(entry.envelope_path, (index, index))
    assert [e.envelope()["n"] for e in spool.pending()] == [0, 1, 2]


def test_survives_a_restart(tmp_path):
    """进程重启后队列还在——这正是「先落盘再上传」的全部意义。"""
    Spool(tmp_path).enqueue(key="sess-000001", envelope={"a": 1}, media=b"y")
    assert len(Spool(tmp_path).pending()) == 1


def test_orphan_envelope_is_cleaned_up(tmp_path):
    """媒体文件没了的孤儿信封会被清掉，不然每轮 drain 都要失败一次。"""
    spool = Spool(tmp_path)
    entry = spool.enqueue(key="sess-000001", envelope={"a": 1}, media=b"y")
    entry.media_path.unlink()
    assert spool.pending() == []
    assert not entry.envelope_path.exists()


def test_rejected_entries_are_kept_not_deleted(tmp_path):
    """后端拒收的条目挪进 rejected/：删掉就再也查不出录到的音频去哪了。"""
    spool = Spool(tmp_path)
    entry = spool.enqueue(key="sess-000001", envelope={"a": 1}, media=b"y")
    spool.reject(entry, "422 契约不兼容")

    assert spool.pending() == []
    rejected = tmp_path / "rejected"
    assert (rejected / "sess-000001.json").exists()
    assert (rejected / "sess-000001.wav").exists()
    assert "422" in (rejected / "sess-000001.reason.txt").read_text("utf-8")


def test_unsafe_keys_cannot_escape_the_spool_dir(tmp_path):
    """幂等键会变成文件名，路径分隔符必须被挡掉。"""
    spool = Spool(tmp_path)
    entry = spool.enqueue(key="../../etc/passwd", envelope={}, media=b"z")
    assert entry.envelope_path.parent == spool.pending_dir
    assert "/" not in entry.key


def test_claim_is_once_per_message(tmp_path):
    spool = Spool(tmp_path)
    assert spool.claim("msg-1") is True
    assert spool.claim("msg-1") is False
    assert spool.outcome_of("msg-1") == ""      # 占了坑，还没跑完
    assert spool.outcome_of("msg-2") is None    # 没见过


def test_outcome_survives_restart_so_duplicates_can_be_answered(tmp_path):
    """至少一次投递 + 采集器重启：重投的请求要能补发上次的终态，而不是重录一段。"""
    spool = Spool(tmp_path)
    spool.claim("msg-1")
    spool.record_outcome("msg-1", "EXECUTED")

    reopened = Spool(tmp_path)
    assert reopened.claim("msg-1") is False
    assert reopened.outcome_of("msg-1") == "EXECUTED"
