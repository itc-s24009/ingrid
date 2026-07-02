import os
import json
import time
from flask import Flask, request, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# ==============================================================================
# データベース接続設定 (Vercel & Neon用 - 標準psycopg2接続)
# ==============================================================================
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # 接続文字列のプロトコル名を標準的な postgresql:// に統一
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
else:
    # ローカル検証用のフォールバック (SQLite)
    database_url = "sqlite:///local_combos.db"

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# コンボ保存用データベースモデル
class Combo(db.Model):
    __tablename__ = 'combos'
    id = db.Column(db.String(50), primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    start_type = db.Column(db.String(50), nullable=False)
    drive_start = db.Column(db.Integer, nullable=False)
    drive_cost = db.Column(db.Integer, nullable=False)
    symbol_start = db.Column(db.Integer, nullable=False)
    symbol_cost = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.Text)
    moves = db.Column(db.JSON, nullable=False)  # JSON型としてリストを格納
    damage = db.Column(db.Integer, nullable=False)

# エラー特定用のグローバル変数
_db_initialized = False
db_init_error = None

@app.before_request
def create_tables():
    global _db_initialized, db_init_error
    if not _db_initialized:
        try:
            db.create_all()
            _db_initialized = True
            db_init_error = None
        except Exception as e:
            # エラーが発生した場合、メッセージを記録してクラッシュを抑止
            db_init_error = str(e)
            app.logger.error(f"Database initialization failed: {e}")

# ==============================================================================
# 正確なフレーム・CDR・補正仕様のデータベース (SA2補正をすべて1打目に固定 ＆ コンボ無視対応)
# ==============================================================================
MOVES_DB = {
    # システムアクション
    "DR": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "インパクト": {"damage": 800, "start_correction": 20, "cdr": False, "type": "H"},
    "インパクト壁やられ": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "ジャストパリィ": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "ドライブ回復1P": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},

    # 通常技・特殊技 (CDR可能/不可能を厳密に定義)
    "弱P": {"damage": 300, "start_correction": 20, "cdr": True, "startup": 4, "active": 3, "recovery": 7, "advantage": 5, "type": "L"},
    "弱K": {"damage": 300, "start_correction": 20, "cdr": True, "startup": 5, "active": 3, "recovery": 11, "advantage": 2, "type": "L"},
    "中P": {"damage": 600, "start_correction": 0, "cdr": True, "startup": 6, "active": 5, "recovery": 13, "advantage": 1, "type": "M"},
    "中K": {"damage": 700, "start_correction": 0, "cdr": True, "startup": 8, "active": 4, "recovery": 16, "advantage": 3, "type": "M"},
    "強P": {"damage": 900, "start_correction": 20, "cdr": False, "startup": 12, "active": 4, "recovery": 20, "advantage": 3, "type": "H"},
    "強K": {"damage": 800, "start_correction": 0, "cdr": False, "startup": 9, "active": 9, "recovery": 19, "advantage": 4, "type": "H"},
    "屈弱P": {"damage": 300, "start_correction": 20, "cdr": True, "startup": 4, "active": 2, "recovery": 9, "advantage": 4, "type": "L"},
    "屈弱K": {"damage": 200, "start_correction": 20, "cdr": False, "startup": 5, "active": 2, "recovery": 10, "advantage": 3, "type": "L"},
    "屈中P": {"damage": 600, "start_correction": 0, "cdr": True, "startup": 7, "active": 4, "recovery": 12, "advantage": 6, "type": "M"},
    "屈中K": {"damage": 500, "start_correction": 20, "cdr": True, "startup": 8, "active": 3, "recovery": 19, "advantage": 1, "type": "M"},
    "屈強P": {"damage": 800, "start_correction": 0, "cdr": True, "startup": 12, "active": 3, "recovery": 20, "advantage": 1, "type": "H"},
    "屈強K": {"damage": 900, "start_correction": 0, "cdr": False, "startup": 10, "active": 3, "recovery": 25, "advantage": 0, "type": "H", "down": True},
    "エアリートス": {"damage": 700, "start_correction": 0, "cdr": True, "combo_correction": 20, "type": "S"},
    
    # 追加の通常技
    "中段": {"damage": 600, "start_correction": 0, "cdr": False, "startup": 21, "active": 4, "recovery": 16, "advantage": 3, "type": "M"},
    "引中Kタゲコン1": {"damage": 700, "start_correction": 0, "cdr": False, "startup": 9, "active": 3, "recovery": 21, "advantage": -99, "type": "M"},
    "引中Kタゲコン2": {"damage": 800, "start_correction": 0, "cdr": False, "startup": 9, "active": 3, "recovery": 21, "advantage": -99, "type": "M"},
    "前強P": {"damage": 900, "start_correction": 0, "cdr": False, "startup": 17, "active": 3, "recovery": 21, "advantage": -99, "type": "H"},
    "引強P": {"damage": 1600, "start_correction": 0, "cdr": True, "startup": 14, "active": 3, "recovery": 20, "advantage": 5, "type": "H"},
    "引強Pタゲコン1": {"damage": 800, "start_correction": 0, "cdr": True, "startup": 14, "active": 3, "recovery": 20, "advantage": 5, "type": "H"},
    "引強Pタゲコン2": {"damage": 800, "start_correction": 0, "cdr": True, "startup": 14, "active": 3, "recovery": 20, "advantage": 5, "type": "H"},
    
    # 必殺技 (サンシュート系はすべて始動補正20%コンボ補正20%に統一)
    "弱サンシュート": {"damage": 700, "start_correction": 20, "cdr": False, "combo_correction": 20, "type": "S"},
    "中サンシュート": {"damage": 700, "start_correction": 20, "cdr": False, "combo_correction": 20, "type": "S"},
    "強サンシュート": {"damage": 700, "start_correction": 20, "cdr": False, "combo_correction": 20, "type": "S"},
    "弱ODサンシュート": {"damage": 1000, "start_correction": 20, "cdr": False, "combo_correction": 20, "type": "S"},
    "強ODサンシュート": {"damage": 1000, "start_correction": 20, "cdr": False, "combo_correction": 20, "type": "S"},
    
    "弱サンフレア": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "Lv0サンフレア": {"damage": 900, "start_correction": 30, "cdr": False, "combo_correction": 20, "type": "S"},
    "Lv1サンフレア": {"damage": 1100, "start_correction": 30, "cdr": False, "combo_correction": 20, "type": "S"},
    "Lv2サンフレア": {"damage": 1350, "start_correction": 30, "cdr": False, "combo_correction": 20, "type": "S"},
    "Lv3サンフレア": {"damage": 1800, "start_correction": 30, "cdr": False, "combo_correction": 20, "type": "S"},
    
    "弱ソーラーフレア": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "Lv0ソーラーフレア": {"damage": 900, "start_correction": 20, "cdr": False, "combo_correction": 0, "type": "S"},
    "Lv1ソーラーフレア": {"damage": 1100, "start_correction": 20, "cdr": False, "combo_correction": 0, "type": "S"},
    "Lv2ソーラーフレア": {"damage": 1350, "start_correction": 20, "cdr": False, "combo_correction": 0, "type": "S"},
    "Lv3ソーラーフレア": {"damage": 1800, "start_correction": 20, "cdr": False, "combo_correction": 0, "type": "S"},
    
    "弱サンライズ": {"damage": 1000, "start_correction": 20, "cdr": False, "type": "S"},
    "中サンライズ": {"damage": 1200, "start_correction": 0, "cdr": False, "combo_correction": 20, "type": "S"},
    "強サンライズ": {"damage": 1300, "start_correction": 20, "cdr": False, "combo_correction": 20, "type": "S"},
    "ODサンライズ": {"damage": 1600, "start_correction": 0, "cdr": False, "combo_correction": 20, "type": "S"},
    "前サンパニッシュ": {"damage": 1000, "start_correction": 0, "cdr": False, "type": "S"},
    "上サンパニッシュ": {"damage": 1100, "start_correction": 0, "cdr": False, "type": "S"},

    # SA1 (最低保証30% / 即時補正20%)
    "SA1_Lv0": {"damage": 1900, "start_correction": 0, "cdr": False, "minimum_guarantee": 30, "immediate_correction": 20, "type": "S"},
    "SA1_Lv1": {"damage": 2300, "start_correction": 0, "cdr": False, "minimum_guarantee": 30, "immediate_correction": 20, "type": "S"},
    "SA1_Lv2": {"damage": 2700, "start_correction": 0, "cdr": False, "minimum_guarantee": 30, "immediate_correction": 20, "type": "S"},

    # SA2発動演出 (0ダメージ・システムユーティリティ扱い)
    "SA2発動_Lv0": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "SA2発動_Lv1": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "SA2発動_Lv2": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},

    # SA2個別分割ヒット (最低保証40% / 即時補正20% / combo_correctionにより100%➔60%始動を実現)
    "SA2_1打目": {"damage": 500, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "combo_correction": 30, "type": "S"},
    "SA2_2打目": {"damage": 500, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},
    "SA2_3打目": {"damage": 600, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},
    "SA2_4打目": {"damage": 800, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},
    "SA2_5打目": {"damage": 1000, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},

    # SA3 / CA (最低保証50% / 即時補正20%)
    "SA3": {"damage": 4000, "start_correction": 0, "cdr": False, "minimum_guarantee": 50, "immediate_correction": 20, "type": "S"},
    "CA": {"damage": 4500, "start_correction": 0, "cdr": False, "minimum_guarantee": 50, "immediate_correction": 20, "type": "S"}
}

# ==============================================================================
# データファイル管理
# ==============================================================================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"combos": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ==============================================================================
# 順次シミュレーションベースのリソース計算 (最大値を超えないための制限)
# ==============================================================================
def py_simulate_resources_sequentially(moves, start_drive, start_symbols):
    drive_curr = start_drive
    symbol_curr = start_symbols
    is_invalid = False
    
    for m in moves:
        name = m['name']
        
        # --- GAINS ---
        if name == "ドライブ回復1P":
            drive_curr = min(6, drive_curr + 1)
            continue
        if name in ["弱サンフレア", "弱ソーラーフレア"]:
            symbol_curr = min(4, symbol_curr + 1)
            continue
            
        # --- COSTS ---
        if m.get('cdr', False):
            if drive_curr <= 0:
                is_invalid = True
            drive_curr -= 3
        if name == "DR":
            if drive_curr <= 0:
                is_invalid = True
            drive_curr -= 1  # DR消費を1Pに修正
        if "OD" in name:
            if drive_curr <= 0:
                is_invalid = True
            drive_curr -= 2
            
        if name.startswith("SA2発動"):
            if "Lv1" in name:
                if symbol_curr < 1:
                    is_invalid = True
                symbol_curr -= 1
            elif "Lv2" in name:
                if symbol_curr < 2:
                    is_invalid = True
                symbol_curr -= 2
            continue
            
        if ("サンフレア" in name or "ソーラーフレア" in name) and not name.startswith("弱"):
            level = 0
            if "Lv1" in name: level = 1
            elif "Lv2" in name: level = 2
            elif "Lv3" in name: level = 3
            
            if level == 1:
                if symbol_curr >= 2:
                    if drive_curr <= 0:
                        is_invalid = True
                    drive_curr -= 2
                elif symbol_curr == 1:
                    symbol_curr -= 1
                else:
                    if drive_curr <= 0:
                        is_invalid = True
                    drive_curr -= 2
            elif level == 2:
                if symbol_curr >= 2:
                    symbol_curr -= 2
                elif symbol_curr == 1:
                    if drive_curr <= 0:
                        is_invalid = True
                    drive_curr -= 2
                    symbol_curr -= 1
                else:
                    is_invalid = True
            elif level == 3:
                if symbol_curr >= 2:
                    if drive_curr <= 0:
                        is_invalid = True
                    drive_curr -= 2
                    symbol_curr -= 2
                else:
                    is_invalid = True
                    
        # バーンアウトした後はドライブが0未満にならずに固定
        if drive_curr < 0:
            drive_curr = 0
            
    return drive_curr, symbol_curr, is_invalid

# ==============================================================================
# バックエンド計算・詳細生成ロジック (SA2分割ヒット補正スルー)
# ==============================================================================
def py_calculate_damage(moves, start_type, min_limit=10):
    if not moves:
        return 0
    total_damage = 0
    current_corr = 100
    cdr_active = False
    next_reduction_bonus = 0
    actual_hit_index = 0
    sa2_saved_corr = 100  # SA2の1打目の最終補正を保存する変数
    
    # 始動技情報の特定 (システムアクション以外の最初の打撃技)
    first_actual_name = next((m['name'] for m in moves if m['name'] not in ["DR", "インパクト壁やられ", "ジャストパリィ", "ドライブ回復1P", "弱サンフレア", "弱ソーラーフレア"] and not m['name'].startswith("SA2発動")), None)
    if not first_actual_name:
        return 0
    first_move = MOVES_DB.get(first_actual_name)
    if not first_move:
        return 0
    start_correction = first_move['start_correction']
    first_move_type = first_move.get('type', 'L')
    
    # 特殊な最初の手数でのグローバルデバフ判定
    first_name = moves[0]['name'] if moves else ""
    impact_wall_active = (first_name == "インパクト壁やられ")
    just_parry_active = (first_name == "ジャストパリィ")
    
    for i, item in enumerate(moves):
        name = item['name']
        if name in ["DR", "インパクト壁やられ", "ジャストパリィ", "ドライブ回復1P", "弱サンフレア", "弱ソーラーフレア"] or name.startswith("SA2発動"):
            if name == "DR":
                cdr_active = True
            continue
            
        move = MOVES_DB.get(name)
        if not move:
            continue
        
        # --- SA2 2〜5打目の特殊処理 (補正を一切計算・加算せず、1打目の補正をそのまま適用) ---
        if name in ["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"]:
            final_corr = sa2_saved_corr
            base_damage = item.get('custom_damage', move['damage'])
            hit_damage = int(base_damage * final_corr / 100)
            total_damage += hit_damage
            continue
            
        base_corr = current_corr
        if actual_hit_index > 0: # 実際のコンボ打撃順で判定！
            decrease = 10
            if actual_hit_index == 1:
                # 始動補正の無い弱攻撃を始動にした際、2発目は90%
                if first_move_type == 'L' and start_correction == 0:
                    decrease = 10
                else:
                    decrease = start_correction
            elif actual_hit_index == 2:
                decrease = 10 if start_correction > 0 else 20
                
            # コンボ補正の適用 (Hit 3以降の最初の減少ステップのみ消費して適用)
            if next_reduction_bonus > 0 and actual_hit_index >= 2:
                if actual_hit_index == 2:
                    decrease = next_reduction_bonus + (0 if start_correction > 0 else 10)
                else:
                    decrease = next_reduction_bonus
                next_reduction_bonus = 0 # 消費したためクリア
                
            base_corr = max(10, current_corr - decrease)
            
            # 即時補正の永続適用
            if actual_hit_index > 0:
                imm = move.get('immediate_correction', 0)
                base_corr = base_corr - imm
                
            current_corr = base_corr
            
        multiplier = 1.0
        if cdr_active:
            multiplier *= 0.85
        if impact_wall_active:
            multiplier *= 0.80
        if just_parry_active:
            multiplier *= 0.50
            
        final_corr = int(base_corr * multiplier)
        
        # 即時補正の減算 (2発目以降)
        if actual_hit_index > 0:
            final_corr = final_corr - move.get('immediate_correction', 0)
            
        # 最低保証上限の適用 (乗算補正がある場合は10%を基準にして乗算スケーリング)
        current_min_limit = max(1, int(10 * multiplier))
        min_limit_for_move = max(current_min_limit, move.get('minimum_guarantee', 0))
        final_corr = max(min_limit_for_move, final_corr)
        
        # 単発ダメージをカスタム設定から、もしくはデフォルトDBから取得
        hit_damage = item.get('custom_damage', move['damage'])
        
        # ODサンライズ➔SA2発動、SA3、CA への派生時ダメージ上書き処理
        if name == "ODサンライズ" and i + 1 < len(moves):
            next_name = moves[i + 1]['name']
            if next_name.startswith("SA2発動") or next_name in ["SA3", "CA"]:
                hit_damage = 900
        
        if actual_hit_index == 0:
            if start_type in ['punish', 'counter']:
                hit_damage = int(hit_damage * 1.2)
        else:
            hit_damage = int(hit_damage * final_corr / 100)
            
        total_damage += hit_damage
        
        # 新しいコンボ補正の検出 (0上書き防止)
        new_bonus = move.get('combo_correction', 0)
        if new_bonus > 0:
            next_reduction_bonus = new_bonus
            
        # SA2の1打目の補正を保存
        if name == "SA2_1打目":
            sa2_saved_corr = final_corr
            
        actual_hit_index += 1
        
        if item.get('cdr', False):
            cdr_active = True
            
    return total_damage

def py_get_combo_details(moves, start_type, min_limit=10):
    if not moves:
        return []
    steps = []
    current_corr = 100
    cdr_active = False
    next_reduction_bonus = 0
    actual_hit_index = 0
    sa2_saved_corr = 100
    
    first_actual_name = next((m['name'] for m in moves if m['name'] not in ["DR", "インパクト壁やられ" , "ジャストパリィ", "ドライブ回復1P", "弱サンフレア", "弱ソーラーフレア"] and not m['name'].startswith("SA2発動")), None)
    if not first_actual_name:
        for item in moves:
            steps.append({
                "hit": "-", "name": item['name'], "base_damage": "-", "decrease": "-", "base_corr": "-", "cdr_active": False, "final_corr": "-", "hit_damage": "-", "note": "システム発動"
            })
        return steps
        
    first_move = MOVES_DB.get(first_actual_name)
    if not first_move:
        return []
    start_correction = first_move['start_correction']
    first_move_type = first_move.get('type', 'L')
    
    first_name = moves[0]['name'] if moves else ""
    impact_wall_active = (first_name == "インパクト壁やられ")
    just_parry_active = (first_name == "ジャストパリィ")
    
    for i, item in enumerate(moves):
        name = item['name']
        if name in ["DR", "インパクト壁やられ", "ジャストパリィ", "ドライブ回復1P", "弱サンフレア", "弱ソーラーフレア"] or name.startswith("SA2発動"):
            if name == "DR":
                cdr_active = True
            steps.append({
                "hit": "-", "name": name, "base_damage": "-", "decrease": "-", "base_corr": "-", "cdr_active": False, "final_corr": "-", "hit_damage": "-", "note": "システム発動"
            })
            continue
            
        move = MOVES_DB.get(name)
        if not move:
            continue
        
        # --- SA2 2〜5打目の特殊処理 (補正を一切計算・加算せず、1打目の補正をそのまま適用) ---
        if name in ["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"]:
            final_corr = sa2_saved_corr
            base_damage = item.get('custom_damage', move['damage'])
            hit_damage = int(base_damage * final_corr / 100)
            steps.append({
                "hit": "-",
                "name": name,
                "base_damage": base_damage,
                "decrease": 0,
                "base_corr": "-",
                "cdr_active": cdr_active,
                "final_corr": final_corr,
                "hit_damage": hit_damage,
                "note": "SA2分割ヒット補正固定"
            })
            continue
            
        base_corr = current_corr
        decrease = 0
        if actual_hit_index > 0: # 実際のコンボ打撃順で判定！
            decrease = 10
            if actual_hit_index == 1:
                if first_move_type == 'L' and start_correction == 0:
                    decrease = 10
                else:
                    decrease = start_correction
            elif actual_hit_index == 2:
                decrease = 10 if start_correction > 0 else 20
            if next_reduction_bonus > 0 and actual_hit_index >= 2:
                if actual_hit_index == 2:
                    decrease = next_reduction_bonus + (0 if start_correction > 0 else 10)
                else:
                    decrease = next_reduction_bonus
                next_reduction_bonus = 0 # 消費したためクリア
                
            base_corr = max(10, current_corr - decrease)
            
            # 即時補正の永続適用
            if actual_hit_index > 0:
                imm = move.get('immediate_correction', 0)
                base_corr = base_corr - imm
                
            current_corr = base_corr
            
        multiplier = 1.0
        if cdr_active:
            multiplier *= 0.85
        if impact_wall_active:
            multiplier *= 0.80
        if just_parry_active:
            multiplier *= 0.50
            
        final_corr = int(base_corr * multiplier)
        
        # 単発ダメージの動的取得
        base_damage = item.get('custom_damage', move['damage'])
        
        # ODサンライズ➔SA2、SA3派生補正
        if name == "ODサンライズ" and i + 1 < len(moves):
            next_name = moves[i + 1]['name']
            if next_name.startswith("SA2発動") or next_name in ["SA3", "CA"]:
                base_damage = 900
        
        imm_note = ""
        if actual_hit_index > 0:
            imm = move.get('immediate_correction', 0)
            if imm > 0:
                imm_note = f" (即時補正 -{imm}%)"
            
        min_limit_for_move = max(1, int(10 * multiplier))
        min_limit_for_move = max(min_limit_for_move, move.get('minimum_guarantee', 0))
        if final_corr < min_limit_for_move:
            final_corr = min_limit_for_move
            imm_note += " (最低保証適用)"
        
        note = ""
        if actual_hit_index == 0:
            if start_type in ['punish', 'counter']:
                hit_damage = int(base_damage * 1.2)
                note = "1.2倍"
            else:
                hit_damage = base_damage
        else:
            hit_damage = int(base_damage * final_corr / 100)
            note = imm_note
            
        steps.append({
            "hit": actual_hit_index + 1,
            "name": name,
            "base_damage": base_damage,
            "decrease": decrease,
            "base_corr": base_corr,
            "cdr_active": cdr_active,
            "final_corr": final_corr,
            "hit_damage": hit_damage,
            "note": note
        })
        
        # SA2の1打目の補正を保存
        if name == "SA2_1打目":
            sa2_saved_corr = final_corr
            
        new_bonus = move.get('combo_correction', 0)
        if new_bonus > 0:
            next_reduction_bonus = new_bonus
            
        actual_hit_index += 1
        if item.get('cdr', False):
            cdr_active = True
            
    return steps

# ==============================================================================
# UI テンプレート (Tailwind CSS)
# ==============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>コンボ管理ノート ＆ 計算機</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen text-gray-800 pb-12">
    <div class="max-w-7xl mx-auto px-4 py-6">
        <header class="text-center mb-6">
            <h1 class="text-2xl font-black text-gray-900">🥋 格闘ゲーム コンボ管理ノート</h1>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <!-- 左側：タイムライン入力フォーム -->
            <div class="lg:col-span-5 space-y-4">
                <div class="bg-white rounded-xl shadow p-5 border border-gray-200">
                    <h2 id="form-title" class="text-md font-bold text-gray-900 mb-3">➕ 新しいコンボを登録</h2>
                    
                    <form id="combo-form" action="/add" method="post" class="space-y-3">
                        <input type="hidden" name="combo_id" id="combo-id">
                        <input type="hidden" name="moves_json" id="moves-json" value="[]">

                        <div>
                            <label class="block text-[11px] font-bold text-gray-600 mb-0.5">コンボ名・状況</label>
                            <input type="text" name="title" id="input-title" class="w-full px-3 py-1.5 border rounded-lg focus:ring-1 focus:ring-blue-500 text-sm" placeholder="例: 強Kパニカン始動" required>
                        </div>

                        <!-- 始動属性の設定 -->
                        <div class="grid grid-cols-3 gap-2">
                            <div>
                                <label class="block text-[11px] font-bold text-gray-600 mb-0.5">始動状態</label>
                                <select name="start_type" id="input-start-type" class="w-full px-2 py-1.5 border rounded-lg text-xs" onchange="updateLivePreview()">
                                    <option value="normal">通常ヒット</option>
                                    <option value="counter">カウンター (有利+2)</option>
                                    <option value="punish">パニカン (有利+4)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-[11px] font-bold text-gray-600 mb-0.5">ゲージ</label>
                                <select name="drive_start" id="input-drive-start" class="w-full px-2 py-1.5 border rounded-lg text-xs" onchange="updateLivePreview()">
                                    {% for g in range(6, -1, -1) %}
                                    <option value="{{ g }}">{{ g }}P</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div>
                                <label class="block text-[11px] font-bold text-gray-600 mb-0.5">シンボル</label>
                                <select name="symbol_start" id="input-symbol-start" class="w-full px-2 py-1.5 border rounded-lg text-xs" onchange="updateLivePreview()">
                                    {% for s in range(0, 5) %}
                                    <option value="{{ s }}">{{ s }}個</option>
                                    {% endfor %}
                                </select>
                            </div>
                        </div>

                        <!-- 技選択ボタンエリア -->
                        <div>
                            <label class="block text-[11px] font-bold text-gray-600 mb-1">⚡ 技を追加する</label>
                            <div class="border rounded-lg p-2 bg-gray-50 max-h-64 overflow-y-auto space-y-2">
                                <div>
                                    <span class="text-[10px] font-bold text-gray-400 block mb-1">通常・特殊技</span>
                                    <div class="flex flex-wrap gap-1">
                                        {% for name in ["弱P", "弱K", "中P", "中K", "強P", "強K", "屈弱P", "屈弱K", "屈中P", "屈中K", "屈強P", "屈強K", "中段", "引中Kタゲコン1", "引中Kタゲコン2", "前強P", "引強P", "引強Pタゲコン1", "引強Pタゲコン2", "エアリートス"] %}
                                        <button type="button" data-move-name="{{ name }}" onclick="addMove('{{ name }}')" class="btn-move-add px-2 py-1 bg-white border border-gray-200 rounded text-xs font-semibold shadow-sm transition">{{ name }}</button>
                                        {% endfor %}
                                    </div>
                                </div>
                                <div>
                                    <span class="text-[10px] font-bold text-gray-400 block mb-1">システム ＆ 必殺技</span>
                                    <div class="flex flex-wrap gap-1">
                                        <button type="button" data-move-name="DR" onclick="addMove('DR')" class="btn-move-add px-2 py-1 bg-yellow-500 border border-yellow-600 text-white rounded text-xs font-semibold shadow-sm transition">DR</button>
                                        <button type="button" data-move-name="インパクト" onclick="addMove('インパクト')" class="btn-move-add px-2 py-1 bg-yellow-100 border border-yellow-300 text-yellow-800 rounded text-xs font-semibold shadow-sm transition">インパクト</button>
                                        <button type="button" data-move-name="インパクト壁やられ" onclick="addMove('インパクト壁やられ')" class="btn-move-add px-2 py-1 bg-yellow-100 border border-yellow-300 text-yellow-800 rounded text-xs font-semibold shadow-sm transition">壁やられ(始動)</button>
                                        <button type="button" data-move-name="ジャストパリィ" onclick="addMove('ジャストパリィ')" class="btn-move-add px-2 py-1 bg-yellow-100 border border-yellow-300 text-yellow-800 rounded text-xs font-semibold shadow-sm transition">Jパリィ(始動)</button>
                                        <button type="button" data-move-name="ドライブ回復1P" onclick="addMove('ドライブ回復1P')" class="btn-move-add px-2 py-1 bg-green-100 border border-green-300 text-green-800 rounded text-xs font-semibold shadow-sm transition">1P回復</button>
                                        {% for name in ["弱サンシュート", "中サンシュート", "強サンシュート", "弱ODサンシュート", "強ODサンシュート", "弱サンフレア", "Lv0サンフレア", "Lv1サンフレア", "Lv2サンフレア", "Lv3サンフレア", "弱ソーラーフレア", "Lv0ソーラーフレア", "Lv1ソーラーフレア", "Lv2ソーラーフレア", "Lv3ソーラーフレア", "弱サンライズ", "中サンライズ", "強サンライズ", "ODサンライズ", "前サンパニッシュ", "上サンパニッシュ"] %}
                                        <button type="button" data-move-name="{{ name }}" onclick="addMove('{{ name }}')" class="btn-move-add px-2 py-1 bg-red-50 border border-red-100 text-red-700 rounded text-xs font-semibold shadow-sm transition">{{ name }}</button>
                                        {% endfor %}
                                    </div>
                                </div>
                                <div>
                                    <span class="text-[10px] font-bold text-gray-400 block mb-1">スーパーアーツ (SA)</span>
                                    <div class="flex flex-wrap gap-1">
                                        {% for name in ["SA1_Lv0", "SA1_Lv1", "SA1_Lv2", "SA2発動_Lv0", "SA2発動_Lv1", "SA2発動_Lv2", "SA2_1打目", "SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目", "SA3", "CA"] %}
                                        <button type="button" data-move-name="{{ name }}" onclick="addMove('{{ name }}')" class="btn-move-add px-2 py-1 bg-purple-50 border border-purple-100 text-purple-700 rounded text-xs font-semibold shadow-sm transition">{{ name }}</button>
                                        {% endfor %}
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- タイムライン -->
                        <div>
                            <label class="block text-[11px] font-bold text-gray-600 mb-0.5">➔ コンボタイムライン (タイムライン内で直接ダメージ値を編集できます)</label>
                            <div id="timeline-container" class="border-2 border-dashed border-gray-200 rounded-lg p-2 bg-gray-50 min-h-[70px] flex flex-wrap gap-1.5 items-center">
                                <p id="timeline-placeholder" class="text-xs text-gray-400 w-full text-center py-4">レシピを構築してください</p>
                            </div>
                        </div>

                        <!-- リアルタイムプレビュー -->
                        <div class="bg-blue-50 border border-blue-100 rounded-lg p-3 flex justify-between items-center text-sm">
                            <div>
                                <span class="text-[9px] font-bold text-blue-500 block">合計ダメージ</span>
                                <span id="preview-damage" class="text-xl font-black text-blue-700">0</span>
                            </div>
                            <div class="text-right">
                                <span class="text-[9px] font-bold text-blue-500 block">使用ゲージ / 使用シンボル</span>
                                <span id="preview-resources" class="font-bold text-blue-900">--</span>
                            </div>
                        </div>

                        <!-- 詳細内訳 -->
                        <details class="bg-blue-50/50 border border-blue-100 rounded-lg p-2.5 text-xs">
                            <summary class="cursor-pointer text-blue-700 font-bold hover:text-blue-900 select-none">
                                📊 ダメージ計算の詳細内訳を表示
                            </summary>
                            <div id="live-calculation-details" class="mt-2 space-y-1">
                                <p class="text-xs text-gray-400 text-center py-2">タイムラインに技がありません</p>
                            </div>
                        </details>

                        <div>
                            <label class="block text-[11px] font-bold text-gray-600 mb-0.5">メモ欄</label>
                            <textarea name="notes" id="input-notes" class="w-full px-3 py-1.5 border rounded-lg focus:ring-1 focus:ring-blue-500 text-xs" rows="2" placeholder="コンボ規制対策など..."></textarea>
                        </div>

                        <div class="flex gap-2">
                            <button type="submit" id="submit-btn" class="flex-1 py-2 bg-blue-600 text-white text-xs font-bold rounded-lg hover:bg-blue-700 transition">コンボを登録</button>
                            <button type="button" id="cancel-btn" onclick="cancelEdit()" class="hidden px-4 py-2 bg-gray-200 text-gray-800 text-xs font-bold rounded-lg hover:bg-gray-300">中止</button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- 右側：コンボ一覧 -->
            <div class="lg:col-span-7 space-y-4">
                <div class="bg-white rounded-xl shadow p-3 border border-gray-200">
                    <form action="/" method="get" class="flex flex-wrap gap-2 items-center w-full">
                        <select name="drive_filter" class="px-2 py-1 border rounded text-xs">
                            <option value="all" {% if drive_filter == 'all' or not drive_filter %}selected{% endif %}>使用ゲージ: すべて</option>
                            {% for g in range(0, 7) %}
                            <option value="{{ g }}" {% if drive_filter == g|string %}selected{% endif %}>{{ g }}P使用</option>
                            {% endfor %}
                        </select>
                        <select name="symbol_filter" class="px-2 py-1 border rounded text-xs">
                            <option value="all" {% if symbol_filter == 'all' or not symbol_filter %}selected{% endif %}>使用シンボル: すべて</option>
                            {% for s in range(0, 5) %}
                            <option value="{{ s }}" {% if symbol_filter == s|string %}selected{% endif %}>シンボル {{ s }}個消費</option>
                            {% endfor %}
                        </select>
                        <input type="text" name="search" class="flex-1 px-3 py-1 border rounded text-xs" placeholder="検索" value="{{ search_query or '' }}">
                        <button type="submit" class="px-3 py-1 bg-gray-800 text-white rounded text-xs font-bold">検索</button>
                    </form>
                </div>

                <div class="space-y-3">
                    {% if combos|length == 0 %}
                    <div class="bg-white rounded-xl shadow p-12 text-center border border-gray-200 text-gray-400 text-sm">
                        コンボデータがありません。
                    </div>
                    {% else %}
                        {% for combo in combos %}
                        <div class="bg-white rounded-xl shadow p-5 border border-gray-200 relative">
                            <div class="absolute top-4 right-4 flex gap-1">
                                <button onclick="editCombo('{{ combo.id }}', '{{ combo.title|e }}', '{{ combo.start_type }}', '{{ combo.drive_start }}', '{{ combo.symbol_start }}', '{{ combo.notes|e }}', '{{ combo.raw_moves_json|e }}')" class="px-2 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 text-[10px] font-bold rounded">編集</button>
                                <form action="/delete/{{ combo.id }}" method="post" onsubmit="return confirm('削除しますか？')" class="inline">
                                    <button type="submit" class="px-2 py-1 bg-red-50 hover:bg-red-100 text-red-600 text-[10px] font-bold rounded">削除</button>
                                </form>
                            </div>

                            <div class="mb-1.5">
                                <span class="px-2 py-0.5 bg-gray-200 text-gray-800 text-[9px] font-bold rounded uppercase">
                                    {% if combo.start_type == 'punish' %}パニカン始動 (+4F)
                                    {% elif combo.start_type == 'counter' %}カウンター始動 (+2F)
                                    {% else %}通常始動{% endif %}
                                </span>
                                <h3 class="text-base font-black text-gray-900 mt-0.5">{{ combo.title }}</h3>
                            </div>

                            <div class="flex flex-wrap gap-1.5 mb-2.5">
                                <span class="px-2 py-0.5 bg-red-100 text-red-800 text-xs font-black rounded">💥 {{ combo.damage }} dmg</span>
                                <span class="px-2 py-0.5 text-xs font-bold rounded {{ 'bg-black text-yellow-400' if combo.drive_cost >= 6 else 'bg-blue-100 text-blue-800' }}">
                                    🔵 使用ゲージ: {{ combo.drive_cost }}P {% if combo.drive_cost >= 6 %}(バーンアウト！){% endif %}
                                </span>
                                <span class="px-2 py-0.5 bg-purple-100 text-purple-800 text-xs font-bold rounded">
                                    🔴 使用シンボル: {{ combo.symbol_cost }}個
                                </span>
                            </div>

                            <div class="text-xs bg-gray-900 text-yellow-400 font-mono p-2.5 rounded mb-2 break-all select-all">
                                {% for m in combo.moves %}
                                    {% if loop.index0 > 0 %} ➔ {% endif %}{% if m.cdr %}<span class="text-green-400 font-bold">[CDR]</span>{% endif %}{{ m.name }}
                                {% endfor %}
                            </div>

                            <!-- 保存済みコンボ：詳細計算アコーディオン -->
                            <details class="bg-gray-50 border border-gray-200 rounded-lg mb-2">
                                <summary class="cursor-pointer px-3 py-1.5 text-xs font-bold text-gray-600 hover:text-gray-900 select-none">
                                    📊 計算式の詳細内訳を表示 (クリック)
                                </summary>
                                <div class="px-3 pb-3 pt-1">
                                    <table class="w-full text-left text-[11px] border-collapse">
                                        <thead>
                                            <tr class="border-b border-gray-200 text-gray-500">
                                                <th class="py-1">Hit</th>
                                                <th class="py-1">技名</th>
                                                <th class="py-1 text-right">単発ダメ</th>
                                                <th class="py-1 text-center">減少幅</th>
                                                <th class="py-1 text-center">基本補正</th>
                                                <th class="py-1 text-center">CDR適用</th>
                                                <th class="py-1 text-center">最終補正</th>
                                                <th class="py-1 text-right pr-2">ダメージ</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {% for step in combo.steps %}
                                            <tr class="border-b border-gray-100 py-1">
                                                <td class="py-1 font-bold text-gray-400">{{ step.hit }}</td>
                                                <td class="py-1 font-semibold text-gray-700">{{ step.name }}</td>
                                                <td class="py-1 text-right">
                                                    {{ step.base_damage }}
                                                    {% if step.note %}<span class="text-[9px] text-red-500 font-bold">{{ step.note }}</span>{% endif %}
                                                </td>
                                                <td class="py-1 text-center text-gray-400">{% if step.hit != '-' and step.hit > 1 %}-{{ step.decrease }}%{% else %}-{% endif %}</td>
                                                <td class="py-1 text-center font-mono">{{ step.base_corr }}{% if step.base_corr != '-' %}%{% endif %}</td>
                                                <td class="py-1 text-center">{% if step.cdr_active %}<span class="text-green-600 font-bold">✓</span>{% else %}-{% endif %}</td>
                                                <td class="py-1 text-center font-mono font-bold text-blue-600">{{ step.final_corr }}{% if step.final_corr != '-' %}%{% endif %}</td>
                                                <td class="py-1 text-right font-black text-gray-900 pr-2">{{ step.hit_damage }}</td>
                                            </tr>
                                            {% endfor %}
                                        </tbody>
                                    </table>
                                </div>
                            </details>

                            {% if combo.notes %}
                            <div class="bg-gray-50 border-l-4 border-gray-300 p-2 text-xs text-gray-600 whitespace-pre-wrap">{{ combo.notes }}</div>
                            {% endif %}
                        </div>
                        {% endfor %}
                    {% endif %}
                </div>
            </div>
        </div>
    </div>

    <!-- リアルタイム不整合防止 JavaScript ロジック -->
    <script>
        const MOVES_DB = {{ moves_db_json|safe }};
        let currentMoves = [];

        function addMove(name) {
            if ((name === "インパクト壁やられ" || name === "ジャストパリィ") && currentMoves.length > 0) {
                return;
            }
            const moveData = MOVES_DB[name];
            const defaultDmg = moveData ? moveData.damage : 0;
            currentMoves.push({ name: name, cdr: false, custom_damage: defaultDmg });
            updateLivePreview();
        }

        function removeMove(index) {
            currentMoves.splice(index, 1);
            updateLivePreview();
        }

        function toggleCDR(index) {
            currentMoves[index].cdr = !currentMoves[index].cdr;
            updateLivePreview();
        }

        function updateCustomDamage(index, val) {
            currentMoves[index].custom_damage = parseInt(val) || 0;
            updateLivePreview();
        }

        // 順次リソース計算シミュレーション (DR消費1P化)
        function simulateResourcesSequentially(moves, startDrive, startSymbols) {
            let driveCurr = startDrive;
            let symbolCurr = startSymbols;
            let isInvalid = false;
            
            for (let i = 0; i < moves.length; i++) {
                const name = moves[i].name;
                const item = moves[i];
                
                // --- GAINS ---
                if (name === "ドライブ回復1P") {
                    driveCurr = Math.min(6, driveCurr + 1);
                    continue;
                }
                if (name === "弱サンフレア" || name === "弱ソーラーフレア") {
                    symbolCurr = Math.min(4, symbolCurr + 1);
                    continue;
                }
                
                // --- COSTS ---
                if (item.cdr) {
                    if (driveCurr <= 0) isInvalid = true;
                    driveCurr -= 3;
                }
                if (name === "DR") {
                    if (driveCurr <= 0) isInvalid = true;
                    driveCurr -= 1; // DR消費を1Pに修正
                }
                if (name.includes("OD")) {
                    if (driveCurr <= 0) isInvalid = true;
                    driveCurr -= 2;
                }
                
                if (name.startsWith("SA2発動")) {
                    if (name.includes("Lv1")) {
                        if (symbolCurr < 1) isInvalid = true;
                        symbolCurr -= 1;
                    } else if (name.includes("Lv2")) {
                        if (symbolCurr < 2) isInvalid = true;
                        symbolCurr -= 2;
                    }
                    continue;
                }
                
                if ((name.includes("サンフレア") || name.includes("ソーラーフレア")) && !name.startsWith("弱")) {
                    let level = 0;
                    if (name.includes("Lv1")) level = 1;
                    else if (name.includes("Lv2")) level = 2;
                    else if (name.includes("Lv3")) level = 3;
                    
                    if (level === 1) {
                        if (symbolCurr >= 2) {
                            if (driveCurr <= 0) isInvalid = true;
                            driveCurr -= 2;
                        } else if (symbolCurr === 1) {
                            symbolCurr -= 1;
                        } else {
                            if (driveCurr <= 0) isInvalid = true;
                            driveCurr -= 2;
                        }
                    } else if (level === 2) {
                        if (symbolCurr >= 2) {
                            symbolCurr -= 2;
                        } else if (symbolCurr === 1) {
                            if (driveCurr <= 0) isInvalid = true;
                            driveCurr -= 2;
                            symbolCurr -= 1;
                        } else {
                            isInvalid = true;
                        }
                    } else if (level === 3) {
                        if (symbolCurr >= 2) {
                            if (driveCurr <= 0) isInvalid = true;
                            driveCurr -= 2;
                            symbolCurr -= 2;
                        } else {
                            isInvalid = true;
                        }
                    }
                }
                
                if (driveCurr < 0) {
                    driveCurr = 0;
                }
            }
            
            return { driveRemain: driveCurr, symbolRemain: symbolCurr, isInvalid };
        }

        function updateLivePreview() {
            const startType = document.getElementById('input-start-type').value;
            // 始動値を常に最大(6Pドライブ・シンボル4個)に固定
            const driveStart = 6;
            const symbolStart = 4;

            let damage = 0;
            let currentCorr = 100;
            let cdrActive = false; 
            let nextReductionBonus = 0;
            let actualHitIndex = 0;
            let sa2SavedCorr = 100; // SA2の一発目の補正を記録する

            const res = simulateResourcesSequentially(currentMoves, driveStart, symbolStart);
            const driveRemain = res.driveRemain;
            const symbolRemain = res.symbolRemain;
            const driveCost = driveStart - driveRemain;
            const symbolCost = symbolStart - symbolRemain;

            const firstMoveName = currentMoves.length > 0 ? currentMoves[0].name : "";
            const impactWallActive = (firstMoveName === "インパクト壁やられ");
            const justParryActive = (firstMoveName === "ジャストパリィ");

            // リアルタイム詳細計算書テーブル
            let stepsHTML = `
                <table class="w-full text-left text-[11px] border-collapse mt-2">
                    <thead>
                        <tr class="border-b border-blue-200 text-blue-700">
                            <th class="py-1">Hit</th>
                            <th class="py-1">技名</th>
                            <th class="py-1 text-right">単発ダメ</th>
                            <th class="py-1 text-center">減少幅</th>
                            <th class="py-1 text-center">基本補正</th>
                            <th class="py-1 text-center">CDR適用</th>
                            <th class="py-1 text-center">最終補正</th>
                            <th class="py-1 text-right pr-2">ダメージ</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            for (let i = 0; i < currentMoves.length; i++) {
                const item = currentMoves[i];
                const move = MOVES_DB[item.name];
                if (!move) continue;

                // DRシステムアクション
                if (item.name === "DR") {
                    cdrActive = true;
                    stepsHTML += `
                        <tr class="border-b border-gray-100 py-1 bg-yellow-50/50">
                            <td class="py-1 font-bold text-gray-400">-</td>
                            <td class="py-1 font-bold text-yellow-700">DR (ラッシュ)</td>
                            <td class="py-1 text-right">-</td>
                            <td class="py-1 text-center text-gray-400">-</td>
                            <td class="py-1 text-center font-mono">-</td>
                            <td class="py-1 text-center"><span class="text-green-600 font-bold">✓</span></td>
                            <td class="py-1 text-center font-mono font-bold text-blue-600">-</td>
                            <td class="py-1 text-right font-black text-gray-900 pr-2">-</td>
                        </tr>
                    `;
                    continue;
                }

                // 壁やられ ＆ パリィ始動アクション
                if (item.name === "インパクト壁やられ" || item.name === "ジャストパリィ" || item.name === "ドライブ回復1P" || item.name === "弱サンフレア" || item.name === "弱ソーラーフレア") {
                    stepsHTML += `
                        <tr class="border-b border-gray-100 py-1 bg-yellow-50/50">
                            <td class="py-1 font-bold text-gray-400">-</td>
                            <td class="py-1 font-bold text-yellow-700">${item.name}</td>
                            <td class="py-1 text-right">0</td>
                            <td class="py-1 text-center text-gray-400">-</td>
                            <td class="py-1 text-center font-mono">-</td>
                            <td class="py-1 text-center">-</td>
                            <td class="py-1 text-center font-mono font-bold text-blue-600">-</td>
                            <td class="py-1 text-right font-black text-gray-900 pr-2">0</td>
                        </tr>
                    `;
                    continue;
                }

                // SA2発動アクション処理
                if (item.name.startsWith("SA2発動")) {
                    stepsHTML += `
                        <tr class="border-b border-gray-100 py-1 bg-purple-50/50">
                            <td class="py-1 font-bold text-gray-400">-</td>
                            <td class="py-1 font-bold text-purple-700">${item.name}</td>
                            <td class="py-1 text-right">0</td>
                            <td class="py-1 text-center text-gray-400">-</td>
                            <td class="py-1 text-center font-mono">-</td>
                            <td class="py-1 text-center">-</td>
                            <td class="py-1 text-center font-mono font-bold text-blue-600">-</td>
                            <td class="py-1 text-right font-black text-gray-900 pr-2">0</td>
                        </tr>
                    `;
                    continue;
                }

                // --- SA2 2〜5打目の特殊処理 (補正を一切計算・加算せず、1打目の補正をそのまま適用) ---
                if (["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"].includes(item.name)) {
                    let finalCorr = sa2SavedCorr;
                    let baseDamage = item.custom_damage !== undefined ? item.custom_damage : move.damage;
                    let hitDamage = Math.floor(baseDamage * finalCorr / 100);
                    damage += hitDamage;
                    
                    stepsHTML += `
                        <tr class="border-b border-gray-100 py-1 bg-purple-50/20">
                            <td class="py-1 font-bold text-gray-400">-</td>
                            <td class="py-1 font-semibold">${item.name}</td>
                            <td class="py-1 text-right">${baseDamage}</td>
                            <td class="py-1 text-center text-gray-400">-</td>
                            <td class="py-1 text-center font-mono">-</td>
                            <td class="py-1 text-center">${cdrActive ? '<span class="text-green-600 font-bold">✓</span>' : '-'}</td>
                            <td class="py-1 text-center font-mono font-bold text-blue-600">${finalCorr}%</td>
                            <td class="py-1 text-right font-black text-gray-900 pr-2">${hitDamage}</td>
                        </tr>
                    `;
                    continue;
                }

                let baseCorr = currentCorr;
                let decrease = 0;
                if (actualHitIndex > 0) { // 実際のコンボ打撃順で判定！
                    const firstActualMove = currentMoves.find(m => m.name !== "DR" && m.name !== "インパクト壁やられ" && m.name !== "ジャストパリィ" && m.name !== "ドライブ回復1P" && m.name !== "弱サンフレア" && m.name !== "弱ソーラーフレア" && !m.name.startsWith("SA2発動"));
                    const startCorrection = firstActualMove ? MOVES_DB[firstActualMove.name].start_correction : 0;
                    const firstMoveType = firstActualMove ? (MOVES_DB[firstActualMove.name].type || "L") : "L";

                    decrease = 10;
                    if (actualHitIndex === 1) {
                        if (firstMoveType === 'L' && startCorrection === 0) {
                            decrease = 10;
                        } else {
                            decrease = startCorrection;
                        }
                    } else if (actualHitIndex === 2) {
                        decrease = (startCorrection > 0) ? 10 : 20;
                    }
                    
                    // コンボ補正の適用 (Hit 3以降の最初の減少ステップのみ消費して適用)
                    if (nextReductionBonus > 0 && actualHitIndex >= 2) {
                        if (actualHitIndex === 2) {
                            decrease = nextReductionBonus + (startCorrection > 0 ? 0 : 10);
                        } else {
                            decrease = nextReductionBonus;
                        }
                        nextReductionBonus = 0; // 消費したためクリア
                    }

                    // SA2の2〜5打目は補正減少を行わない
                    if (["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"].includes(item.name)) {
                        decrease = 0;
                    }

                    baseCorr = Math.max(10, currentCorr - decrease);
                    
                    // 即時補正の永続適用 (SA2の2〜5打目は除外)
                    if (actualHitIndex > 0) {
                        let imm = 0;
                        if (["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"].includes(item.name)) {
                            imm = 0;
                        } else {
                            imm = move.immediate_correction || 0;
                        }
                        baseCorr = baseCorr - imm;
                    }
                    
                    currentCorr = baseCorr;
                }

                let multiplier = 1.0;
                if (cdrActive) multiplier *= 0.85;
                if (impactWallActive) multiplier *= 0.80;
                if (justParryActive) multiplier *= 0.50;

                let finalCorr = Math.floor(baseCorr * multiplier);

                let immNote = "";
                if (actualHitIndex > 0) {
                    const imm = move.immediate_correction || 0;
                    if (imm > 0 && !["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"].includes(item.name)) {
                        immNote = ` (即時補正 -${imm}%)`;
                    }
                }

                const currentMinLimit = Math.max(1, Math.floor(10 * multiplier));
                const minLimitForMove = Math.max(currentMinLimit, move.minimum_guarantee || 0);
                if (finalCorr < minLimitForMove) {
                    finalCorr = minLimitForMove;
                    immNote += " (最低保証適用)";
                }

                let baseDamage = item.custom_damage !== undefined ? item.custom_damage : move.damage;

                let noteLabel = "";
                if (item.name === "ODサンライズ" && i + 1 < currentMoves.length) {
                    const nextName = currentMoves[i + 1].name;
                    if (nextName.startsWith("SA2発動") || nextName === "SA3" || nextName === "CA") {
                        baseDamage = 900;
                        noteLabel = "派生900";
                    }
                }

                let hitDamage = baseDamage;
                if (actualHitIndex === 0) {
                    if (startType === 'punish' || startType === 'counter') {
                        hitDamage = Math.floor(hitDamage * 1.2);
                        noteLabel = "x1.2";
                    }
                } else {
                    hitDamage = Math.floor(hitDamage * finalCorr / 100);
                }

                damage += hitDamage;
                
                // 新しいコンボ補正の検出
                const newBonus = move.combo_correction || 0;
                if (newBonus > 0) {
                    nextReductionBonus = newBonus;
                }

                stepsHTML += `
                    <tr class="border-b border-gray-100 py-1">
                        <td class="py-1 font-bold text-gray-500">${actualHitIndex + 1}</td>
                        <td class="py-1 font-semibold">${item.name}</td>
                        <td class="py-1 text-right">${baseDamage}${noteLabel ? ' <span class="text-[9px] text-red-500 font-bold">' + noteLabel + '</span>' : ''}</td>
                        <td class="py-1 text-center text-gray-400">${actualHitIndex > 0 ? '-' + decrease + '%' : '-'}</td>
                        <td class="py-1 text-center font-mono">${baseCorr}%</td>
                        <td class="py-1 text-center">${cdrActive ? '<span class="text-green-600 font-bold">✓</span>' : '-'}</td>
                        <td class="py-1 text-center font-mono font-bold text-blue-600">${finalCorr}% <span class="text-[9px] text-purple-600 font-bold">${immNote}</span></td>
                        <td class="py-1 text-right font-black text-gray-900 pr-2">${hitDamage}</td>
                    </tr>
                `;

                // SA2の一発目の補正を記録保存
                if (item.name === "SA2_1打目") {
                    sa2SavedCorr = finalCorr;
                }

                actualHitIndex++;

                if (item.cdr) {
                    cdrActive = true;
                }
            }

            stepsHTML += `
                    </tbody>
                </table>
            `;

            if (currentMoves.length === 0) {
                stepsHTML = '<p class="text-xs text-gray-400 py-2 text-center">タイムラインに技が追加されていません</p>';
            }

            document.getElementById('live-calculation-details').innerHTML = stepsHTML;

            // ボタンロック（不整合・順次リソース不足制御）
            const addButtons = document.querySelectorAll('.btn-move-add');
            addButtons.forEach(btn => {
                const moveName = btn.getAttribute('data-move-name');
                const move = MOVES_DB[moveName];
                if (!move) return;

                let isLocked = false;

                if ((moveName === "インパクト壁やられ" || moveName === "ジャストパリィ") && currentMoves.length > 0) {
                    isLocked = true;
                }

                // SA2打目ロック判定 (対応発動演出の履歴が無いと打てないように制限)
                if (moveName.startsWith("SA2_")) {
                    const hasSA2_Activation = currentMoves.some(m => m.name.startsWith("SA2発動"));
                    if (!hasSA2_Activation) {
                        isLocked = true;
                    }
                    if (moveName === "SA2_4打目") {
                        const hasLv1_2 = currentMoves.some(m => m.name === "SA2発動_Lv1" || m.name === "SA2発動_Lv2");
                        if (!hasLv1_2) isLocked = true;
                    }
                    if (moveName === "SA2_5打目") {
                        const hasLv2 = currentMoves.some(m => m.name === "SA2発動_Lv2");
                        if (!hasLv2) isLocked = true;
                    }
                }

                // 順次シミュレーションを行い、この技を追加した場合に不整合(isInvalid)が発生しないか検証
                const testCombo = [...currentMoves, { name: moveName, cdr: false }];
                const testSim = simulateResourcesSequentially(testCombo, driveStart, symbolStart);
                if (testSim.isInvalid) {
                    isLocked = true;
                }

                btn.disabled = isLocked;
                if (isLocked) {
                    btn.classList.add('opacity-30', 'cursor-not-allowed');
                } else {
                    btn.classList.remove('opacity-30', 'cursor-not-allowed');
                }
            });

            // タイムライン構築によるゲージおよびシンボルの実際の消費値を表示
            document.getElementById('preview-damage').innerText = damage;
            document.getElementById('preview-resources').innerText = `${driveCost}P / 🔴 ${symbolCost}個`;

            renderTimeline(driveRemain);
            document.getElementById('moves-json').value = JSON.stringify(currentMoves);
        }

        function renderTimeline(driveRemain) {
            const container = document.getElementById('timeline-container');
            container.innerHTML = '';

            if (currentMoves.length === 0) {
                container.innerHTML = '<p id="timeline-placeholder" class="text-xs text-gray-400 w-full text-center py-4">レシピを構築してください</p>';
                return;
            }

            currentMoves.forEach((item, index) => {
                if (index > 0) {
                    const arrow = document.createElement('span');
                    arrow.className = 'text-gray-400 font-bold mx-0.5 text-xs';
                    arrow.innerText = '➔';
                    container.appendChild(arrow);
                }

                const moveData = MOVES_DB[item.name];
                const canCDR = moveData && moveData.cdr === true;

                const block = document.createElement('div');
                block.className = `flex items-center gap-1 bg-white border border-gray-300 rounded px-2 py-0.5 text-xs font-bold shadow-sm transition-all ${
                    item.cdr ? 'bg-green-50 border-green-300 text-green-800' : 'text-gray-700'
                }`;

                let cdrBtn = '';
                if (canCDR) {
                    const isCdrLocked = !item.cdr && driveRemain <= 0;
                    const disabledAttr = isCdrLocked ? 'disabled title="ゲージ不足"' : '';
                    const opacityClass = isCdrLocked ? 'opacity-30 cursor-not-allowed' : 'hover:bg-gray-300';
                    
                    cdrBtn = `<button type="button" onclick="toggleCDR(${index})" ${disabledAttr} class="px-1 py-0.2 bg-gray-200 rounded text-[9px] ${opacityClass}">CDR</button>`;
                }

                const damageInputHTML = (item.name !== "DR" && item.name !== "インパクト壁やられ" && item.name !== "ジャストパリィ" && item.name !== "ドライブ回復1P" && item.name !== "弱サンフレア" && item.name !== "弱ソーラーフレア" && !item.name.startsWith("SA2発動")) 
                    ? `<span class="text-[9px] text-gray-400 font-normal ml-0.5">単:</span><input type="number" oninput="updateCustomDamage(${index}, this.value)" class="w-12 px-0.5 py-0 border rounded text-[10px] text-center font-bold bg-gray-50 focus:bg-white" value="${item.custom_damage}">`
                    : '';

                block.innerHTML = `
                    <span>${item.name}</span>
                    ${damageInputHTML}
                    ${cdrBtn}
                    <button type="button" onclick="removeMove(${index})" class="text-red-500 font-black hover:text-red-700 ml-1 text-sm">×</button>
                `;
                container.appendChild(block);
            });
        }

        function editCombo(id, title, startType, driveStart, symbolStart, notes, rawMovesJson) {
            document.getElementById('form-title').innerText = "📝 コンボを編集";
            document.getElementById('combo-id').value = id;
            document.getElementById('input-title').value = title;
            document.getElementById('input-start-type').value = startType;

            currentMoves = JSON.parse(rawMovesJson);
            currentMoves.forEach(m => {
                if (m.custom_damage === undefined) {
                    m.custom_damage = MOVES_DB[m.name] ? MOVES_DB[m.name].damage : 0;
                }
            });

            updateLivePreview();

            document.getElementById('submit-btn').innerText = "変更を保存";
            document.getElementById('cancel-btn').classList.remove('hidden');
            document.getElementById('combo-form').action = "/edit";
            document.getElementById('combo-form').scrollIntoView({ behavior: 'smooth' });
        }

        function cancelEdit() {
            document.getElementById('form-title').innerText = "➕ 新しいコンボを登録";
            document.getElementById('combo-id').value = "";
            document.getElementById('combo-form').reset();
            currentMoves = [];
            updateLivePreview();

            document.getElementById('submit-btn').innerText = "コンボを登録";
            document.getElementById('cancel-btn').classList.add('hidden');
            document.getElementById('combo-form').action = "/add";
        }
    </script>
</body>
</html>
"""

# ==============================================================================
# サーバールーティング
# ==============================================================================
@app.route('/', methods=['GET'])
def index():
    global db_init_error
    # データベース接続エラーがある場合は、エラー詳細を画面に表示
    if db_init_error:
        return f"""
        <div style="padding: 20px; font-family: sans-serif; background-color: #fff5f5; color: #c53030; border: 1px solid #feb2b2; border-radius: 8px; max-width: 800px; margin: 40px auto;">
            <h3 style="margin-top: 0;">⚠️ データベース接続エラーが発生しました</h3>
            <p>VercelからNeonデータベースへの接続設定、または接続処理中に以下の問題が発生しました：</p>
            <pre style="background: #fff; padding: 15px; border-radius: 4px; border: 1px solid #fed7d7; overflow-x: auto; font-family: monospace; font-size: 13px; color: #2d3748;">{db_init_error}</pre>
            <p style="font-size: 14px; color: #4a5568;">対策：Vercelの設定画面で「DATABASE_URL」環境変数が正しく登録されているか確認してください。</p>
        </div>
        """, 500

    data = load_data()
    combos = data.get('combos', [])
    
    drive_filter = request.args.get('drive_filter')
    symbol_filter = request.args.get('symbol_filter')
    search_query = request.args.get('search')
    
    filtered_combos = []
    for c in combos:
        if drive_filter and drive_filter != 'all':
            if c.get('drive_cost', 0) != int(drive_filter):
                continue
        if symbol_filter and symbol_filter != 'all':
            if c.get('symbol_cost', 0) != int(symbol_filter):
                continue
        if search_query:
            q = search_query.lower()
            in_title = q in c.get('title', '').lower()
            in_notes = q in c.get('notes', '').lower()
            if not (in_title or in_notes):
                continue
                
        # 画面描画用に動的に詳細ステップ計算をバインド
        c['steps'] = py_get_combo_details(c['moves'], c['start_type'])
        filtered_combos.append(c)
        
    return render_template_string(
        HTML_TEMPLATE, 
        combos=filtered_combos, 
        drive_filter=drive_filter, 
        symbol_filter=symbol_filter, 
        search_query=search_query,
        moves_db_json=json.dumps(MOVES_DB)
    )

@app.route('/add', methods=['POST'])
def add():
    data = load_data()
    moves = json.loads(request.form.get('moves_json', '[]'))
    start_type = request.form.get('start_type', 'normal')
    
    # 常に初期リソース最大値として計算
    drive_start = 6
    symbol_start = 4
    
    drive_remain, symbol_remain, is_invalid = py_simulate_resources_sequentially(moves, drive_start, symbol_start)
    drive_cost = drive_start - drive_remain
    symbol_cost = symbol_start - symbol_remain
    
    damage = py_calculate_damage(moves, start_type)
    
    new_combo = {
        "id": str(int(time.time() * 1000)),
        "title": request.form.get('title', '無題'),
        "start_type": start_type,
        "drive_start": drive_start,
        "drive_cost": drive_cost,
        "symbol_start": symbol_start,
        "symbol_cost": symbol_cost,
        "notes": request.form.get('notes', ''),
        "moves": moves,
        "raw_moves_json": json.dumps(moves),
        "damage": damage
    }
    
    data['combos'].append(new_combo)
    save_data(data)
    return redirect(url_for('index'))

@app.route('/edit', methods=['POST'])
def edit():
    data = load_data()
    combo_id = request.form.get('combo_id')
    moves = json.loads(request.form.get('moves_json', '[]'))
    start_type = request.form.get('start_type', 'normal')
    
    # 常に初期リソース最大値として計算
    drive_start = 6
    symbol_start = 4
    
    drive_remain, symbol_remain, is_invalid = py_simulate_resources_sequentially(moves, drive_start, symbol_start)
    drive_cost = drive_start - drive_remain
    symbol_cost = symbol_start - symbol_remain
    
    damage = py_calculate_damage(moves, start_type)
    
    for combo in data['combos']:
        if combo['id'] == combo_id:
            combo['title'] = request.form.get('title', '無題')
            combo['start_type'] = start_type
            combo['drive_start'] = drive_start
            combo['drive_cost'] = drive_cost
            combo['symbol_start'] = symbol_start
            combo['symbol_cost'] = symbol_cost
            combo['notes'] = request.form.get('notes', '')
            combo['moves'] = moves
            combo['raw_moves_json'] = json.dumps(moves)
            combo['damage'] = damage
            break
            
    save_data(data)
    return redirect(url_for('index'))

@app.route('/delete/<combo_id>', methods=['POST'])
def delete(combo_id):
    data = load_data()
    data['combos'] = [c for c in data['combos'] if c['id'] != combo_id]
    save_data(data)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)