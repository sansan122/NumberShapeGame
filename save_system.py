"""
《数与形》存档 / 读档
================================================
把一局爬塔的进度写到一个 JSON 文件里，下次打开接着玩。

存了什么（saves/save_1.json ~ save_3.json，三个槽位）：
    version      存档格式版本号（以后改结构时用来判断能不能读）
    saved_at     存档时间（给人看的）
    seed         生成这张地图用的随机种子
    floor_index  在第几层（0 开始）
    current      当前站在哪个节点
    visited      这一层已经走过哪些节点
    player       生命 / 金币 / 遗物 / 牌库 / 日志
    map_effects  地图副作用（未完待证、负债增量、强制精英）
    floor_stats  每层的战绩统计（打了几场、赢了几场）

为什么地图不用整个存下来？
    因为地图是「种子 -> 地图」的确定性函数：同一个种子跑出来的地图
    一模一样。所以只要记住 seed，读档时重新生成一遍就行，
    存档文件能小很多（几十 KB -> 几 KB）。

如果种子对不上（比如玩家中途换了地图）怎么办？
    会退化成「只恢复玩家状态 + 楼层 + 当前节点」，
    并在地图上记一条日志说明。至少血和牌不会丢。

怎么用：
    from save_system import SaveManager, list_slots
    sm = SaveManager(slot=0)    # 绑定槽 0
    sm.save(game)               # 存到槽 0
    data = sm.load()            # 读槽 0（返回 dict 或 None）
    sm.delete()                 # 删槽 0
    slots = list_slots()        # 看所有槽的状态（菜单用）
"""

import json
import time
from pathlib import Path

import game_env as E
import map_scene as M
from player import Player

# 存档格式版本。改了结构就把这个数 +1，
# 老存档读到版本不对会拒绝加载（而不是崩掉）。
SAVE_VERSION = 1

# 存档目录。
#
# ⚠️ 这里不能再用 `Path(__file__).parent` —— 打包成 exe 之后它指向
# 临时解包目录，那个目录退出就被删，存档等于白存。
#
# game_env.user_data_path() 会优先用「exe 同级的 saves/」（整个文件夹
# 拷走存档跟着走，符合绿色版的直觉），写不了就退回 %APPDATA%。
SAVE_DIR = E.user_data_path("saves")

# 存档槽位数。三个槽，玩家可以同时保留三局不同进度的爬塔。
# 槽位号从 0 开始，对应文件 save_1.json / save_2.json / save_3.json。
SLOT_COUNT = 3

# 兼容旧版：以前只有一个 save.json。迁到多槽后，第一次读旧档时
# 把它认作「槽 0」，这样老玩家不会丢进度。
LEGACY_FILE = SAVE_DIR / "save.json"


def slot_file(slot):
    """槽位号 -> 存档文件路径。slot 从 0 开始。"""
    return SAVE_DIR / ("save_%d.json" % (slot + 1))


class SaveManager:
    """存档文件的读写。所有方法都不抛异常给上层，
    失败时返回 False / None，并把原因写在 self.last_error 里。

    支持多个存档槽：构造时传 slot（0 开始）就绑定那个槽的文件，
    不传就默认槽 0。要一次看所有槽，用模块级的 list_slots()。
    """

    def __init__(self, path=None, slot=0):
        if path is not None:
            self.path = Path(path)
        else:
            self.path = slot_file(slot)
        self.slot = slot
        self.last_error = ""

    # ==================== 查询 ====================
    def exists(self):
        return self.path.exists()

    def info(self):
        """只读存档头部信息，用来在菜单上显示「第几层 / 什么时间」。
        不构造 Player，读坏了也不影响主流程。"""
        data = self._read_raw()
        if data is None:
            return None
        p = data.get("player", {})
        return {
            "saved_at": data.get("saved_at", "?"),
            "floor_index": data.get("floor_index", 0),
            "floor_name": data.get("floor_name", ""),
            "hp": p.get("hp", 0),
            "max_hp": p.get("max_hp", 0),
            "gold": p.get("gold", 0),
            "deck_size": len(p.get("deck", [])),
            "seed": data.get("seed"),
        }

    # ==================== 写 ====================
    def save(self, game):
        """把当前 Game 存下来。成功返回 True。"""
        self.last_error = ""
        try:
            data = self._snapshot(game)
            # 注意：要建的是「这份存档所在目录」，不是模块级的 SAVE_DIR。
            # 否则自定义路径的存档（比如测试里的临时文件）会顺带
            # 在项目根下建一个空的 saves/ 目录。
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再改名：万一写到一半断电，
            # 也不会把原来那份好存档毁掉。
            tmp = self.path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
            return True
        except Exception as e:              # noqa: BLE001
            self.last_error = "%s: %s" % (type(e).__name__, e)
            return False

    def _snapshot(self, game):
        """从 game 里提取要存的东西。"""
        mp = game.map
        return {
            "version": SAVE_VERSION,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seed": mp.data.get("seed"),
            "floor_index": mp.floor_index,
            "floor_name": mp.floor.get("name", ""),
            "current": mp.current,
            "visited": sorted(mp.visited),
            "player": game.player.to_dict(),
            "map_effects": {
                "hide_next": mp.hide_next,
                "enemy_hp_mult": mp.enemy_hp_mult,
                "force_elite_next": getattr(mp, "force_elite_next", False),
            },
            "floor_stats": getattr(game, "floor_stats", {}),
        }

    # ==================== 读 ====================
    def load(self):
        """读存档，返回 dict（还没变成对象）。
        存档不存在或版本不对就返回 None。"""
        self.last_error = ""
        data = self._read_raw()
        if data is None:
            return None
        if data.get("version") != SAVE_VERSION:
            self.last_error = ("存档版本 %s，当前程序只认 %d"
                               % (data.get("version"), SAVE_VERSION))
            return None
        return data

    def _read_raw(self):
        """只做「读文件 + 解析 JSON」这两件事，带错误处理。"""
        if not self.path.exists():
            self.last_error = "没有存档"
            return None
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            # 存档写坏了：改名留档，别直接删，用户可能想看看
            self.last_error = "存档损坏：%s" % e
            try:
                self.path.replace(self.path.with_suffix(".json.bad"))
            except OSError:
                pass
            return None
        except OSError as e:
            self.last_error = "读不了存档：%s" % e
            return None

    # ==================== 删 ====================
    def delete(self):
        """通关或重开后清掉存档。"""
        if self.path.exists():
            try:
                self.path.unlink()
                return True
            except OSError as e:
                self.last_error = "删不掉：%s" % e
                return False
        return True


def _migrate_legacy_once():
    """把旧版单文件 save.json 迁到槽 0（只迁一次，迁完就删旧文件）。

    旧版存档叫 save.json，多槽后叫 save_1.json。为了不丢老玩家的进度，
    第一次跑的时候发现 save.json 还在、而 save_1.json 还没有，
    就把旧档认作槽 0。删旧文件失败不影响，下次还会再试。
    """
    if not LEGACY_FILE.exists():
        return
    target = slot_file(0)
    if target.exists():
        # 槽 0 已经有档了，旧文件让位（不覆盖，宁可留着也不丢）
        return
    try:
        LEGACY_FILE.rename(target)
    except OSError:
        # 改名失败（可能被占用），下次再试；旧档至少还在
        pass


def list_slots():
    """返回所有槽位的状态列表，供菜单显示。

    返回 [ {slot, info, exists}, ... ]，info 是 SaveManager.info() 的结果
    （不存在则为 None）。顺带做一次旧档迁移。
    """
    _migrate_legacy_once()
    result = []
    for s in range(SLOT_COUNT):
        mgr = SaveManager(slot=s)
        info = mgr.info()
        result.append({
            "slot": s,
            "exists": mgr.exists(),
            "info": info,
        })
    return result


def build_game_data(save, map_data=None):
    """
    把存档 dict 翻译成「造 Game 要用的材料」。

    返回一个 dict：
        player          已经还原好的 Player
        floor_index     从第几层开始
        seed_ok         True = 地图种子对得上，地图是真的同一张
        map_data        用哪个 map 数据（对不上就用当前 map.json）
        current/visited 要恢复到哪个节点
        map_effects     地图副作用
        floor_stats     战绩
    """
    p = Player.from_dict(save["player"])

    seed_saved = save.get("seed")

    if map_data is None:
        # 没传 map 数据就自己按**存档里的种子**重新生成一张。
        # 注意：这里以前是 M.load_map() 读 out/map.json —— 那个文件是静态的，
        # 游戏改成「每局现生成地图」之后就读不回来了，
        # 表现为读档后地图变回默认那张（seed 20260915），角色状态在、
        # 但站位和路线全对不上。必须按 seed 重生。
        map_data = _regenerate_map(seed_saved)

    seed_now = (map_data or {}).get("seed")
    seed_ok = (seed_saved is not None and seed_saved == seed_now)

    return {
        "player": p,
        "floor_index": save.get("floor_index", 0),
        "seed_ok": seed_ok,
        "map_data": map_data,
        "current": save.get("current"),
        "visited": set(save.get("visited", [])),
        "map_effects": save.get("map_effects", {}),
        "floor_stats": save.get("floor_stats", {}),
    }


def _regenerate_map(seed):
    """按种子重新生成一张地图（读档用）。

    拿不到生成器（比如 map_tools 不见了）就退回磁盘上的 map.json，
    至少不会因为读档而崩掉。
    """
    if seed is None:
        return _load_static_map()
    try:
        import build_map as B
        return B.build_in_memory(seed=seed)
    except Exception:                       # noqa: BLE001
        return _load_static_map()


def _load_static_map():
    try:
        return M.load_map()
    except FileNotFoundError:
        return None
