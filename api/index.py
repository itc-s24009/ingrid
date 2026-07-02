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

# テーブルの遅延作成および競合エラーのハンドリング
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
            error_str = str(e)
            if "already exists" in error_str or "duplicate key" in error_str:
                _db_initialized = True
                db_init_error = None
            else:
                db_init_error = error_str
                app.logger.error(f"Database initialization failed: {e}")

# ==============================================================================
# 正確なフレーム・CDR・補正仕様のデータベース (コンボ補正持続・SA2補正調整版)
# ==============================================================================
MOVES_DB = {
    # システムアクション
    "DR": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "インパクト": {"damage": 800, "start_correction": 20, "cdr": False, "type": "H"},
    "インパクト壁やられ": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "ジャストパリィ": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "ドライブ回復1P": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},

    # 通常技・特殊技
    "弱P": {"damage": 300, "start_correction": 20, "cdr": True, "startup": 4, "active": 3, "recovery": 7, "advantage": 5, "type": "L"},
    "弱K": {"damage": 300, "start_correction": 20, "cdr": True, "startup": 5, "active": 3, "recovery": 11, "advantage": 2, "type": "L"},
    "中Pタゲコン1": {"damage": 600, "start_correction": 0, "cdr": True, "startup": 6, "active": 5, "recovery": 13, "advantage": 1, "type": "M"},
    "中Pタゲコン2": {"damage": 700, "start_correction": 0, "cdr": True, "combo_correction": 20, "type": "S"},
    "中K": {"damage": 700, "start_correction": 0, "cdr": True, "startup": 8, "active": 4, "recovery": 16, "advantage": 3, "type": "M"},
    "強P": {"damage": 900, "start_correction": 20, "cdr": False, "startup": 12, "active": 4, "recovery": 20, "advantage": 3, "type": "H"},
    "強K": {"damage": 800, "start_correction": 0, "cdr": False, "startup": 9, "active": 9, "recovery": 19, "advantage": 4, "type": "H"},
    "屈弱P": {"damage": 300, "start_correction": 20, "cdr": True, "startup": 4, "active": 2, "recovery": 9, "advantage": 4, "type": "L"},
    "屈弱K": {"damage": 200, "start_correction": 20, "cdr": False, "startup": 5, "active": 2, "recovery": 10, "advantage": 3, "type": "L"},
    "屈中P": {"damage": 600, "start_correction": 0, "cdr": True, "startup": 7, "active": 4, "recovery": 12, "advantage": 6, "type": "M"},
    "屈中K": {"damage": 500, "start_correction": 20, "cdr": True, "startup": 8, "active": 3, "recovery": 19, "advantage": 1, "type": "M"},
    "屈強P": {"damage": 800, "start_correction": 0, "cdr": True, "startup": 12, "active": 3, "recovery": 20, "advantage": 1, "type": "H"},
    "屈強K": {"damage": 900, "start_correction": 0, "cdr": False, "startup": 10, "active": 3, "recovery": 25, "advantage": 0, "type": "H", "down": True},
    
    # 追加の通常技
    "中段": {"damage": 600, "start_correction": 0, "cdr": False, "startup": 21, "active": 4, "recovery": 16, "advantage": 3, "type": "M"},
    "引中Kタゲコン1": {"damage": 700, "start_correction": 0, "cdr": False, "startup": 9, "active": 3, "recovery": 21, "advantage": -99, "type": "M"},
    "引中Kタゲコン2": {"damage": 800, "start_correction": 0, "cdr": False, "startup": 9, "active": 3, "recovery": 21, "advantage": -99, "type": "M"},
    "前強P": {"damage": 900, "start_correction": 0, "cdr": False, "startup": 17, "active": 3, "recovery": 21, "advantage": -99, "type": "H"},
    "引強Pタゲコン1": {"damage": 800, "start_correction": 0, "cdr": True, "startup": 14, "active": 3, "recovery": 20, "advantage": 5, "type": "H"},
    "引強Pタゲコン2": {"damage": 800, "start_correction": 0, "cdr": True, "startup": 14, "active": 3, "recovery": 20, "advantage": 5, "type": "H"},
    
    # 必殺技
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

    # SA1
    "SA1_Lv0": {"damage": 1900, "start_correction": 0, "cdr": False, "minimum_guarantee": 30, "immediate_correction": 20, "type": "S"},
    "SA1_Lv1": {"damage": 2300, "start_correction": 0, "cdr": False, "minimum_guarantee": 30, "immediate_correction": 20, "type": "S"},
    "SA1_Lv2": {"damage": 2700, "start_correction": 0, "cdr": False, "minimum_guarantee": 30, "immediate_correction": 20, "type": "S"},

    # SA2発動演出
    "SA2発動_Lv0": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "SA2発動_Lv1": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},
    "SA2発動_Lv2": {"damage": 0, "start_correction": 0, "cdr": False, "type": "S"},

    # SA2個別分割ヒット
    "SA2_1打目": {"damage": 500, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "combo_correction": 30, "type": "S"},
    "SA2_2打目": {"damage": 500, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},
    "SA2_3打目": {"damage": 600, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},
    "SA2_4打目": {"damage": 800, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},
    "SA2_5打目": {"damage": 1000, "start_correction": 0, "cdr": False, "minimum_guarantee": 40, "immediate_correction": 20, "type": "S"},

    # SA3 / CA
    "SA3": {"damage": 4000, "start_correction": 0, "cdr": False, "minimum_guarantee": 50, "immediate_correction": 20, "type": "S"},
    "CA": {"damage": 4500, "start_correction": 0, "cdr": False, "minimum_guarantee": 50, "immediate_correction": 20, "type": "S"}
}

# ==============================================================================
# リソース計算ロジック
# ==============================================================================
def py_simulate_resources_sequentially(moves, start_drive, start_symbols):
    drive_curr = start_drive
    symbol_curr = start_symbols
    is_invalid = False
    
    for m in moves:
        name = m['name']
        if name == "ドライブ回復1P":
            drive_curr = min(6, drive_curr + 1)
            continue
        if name in ["弱サンフレア", "弱ソーラーフレア"]:
            symbol_curr = min(4, symbol_curr + 1)
            continue
            
        if m.get('cdr', False):
            if drive_curr <= 0:
                is_invalid = True
            drive_curr -= 3
        if name == "DR":
            if drive_curr <= 0:
                is_invalid = True
            drive_curr -= 1
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
                    
        if drive_curr < 0:
            drive_curr = 0
            
    return drive_curr, symbol_curr, is_invalid

# ==============================================================================
# ダメージ計算ロジック
# ==============================================================================
def py_calculate_damage(moves, start_type, min_limit=10):
    if not moves:
        return 0
    total_damage = 0
    current_corr = 100
    cdr_active = False
    next_reduction_bonus = 0
    actual_hit_index = 0
    sa2_saved_corr = 100
    
    first_actual_name = next((m['name'] for m in moves if m['name'] not in ["DR", "インパクト壁やられ", "ジャストパリィ", "ドライブ回復1P", "弱サンフレア", "弱ソーラーフレア"] and not m['name'].startswith("SA2発動")), None)
    if not first_actual_name:
        return 0
    first_move = MOVES_DB.get(first_actual_name)
    if not first_move:
        return 0
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
            continue
            
        move = MOVES_DB.get(name)
        if not move:
            continue
        
        if name in ["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"]:
            final_corr = sa2_saved_corr
            base_damage = item.get('custom_damage', move['damage'])
            hit_damage = int(base_damage * final_corr / 100)
            total_damage += hit_damage
            continue
            
        base_corr = current_corr
        if actual_hit_index > 0:
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
                next_reduction_bonus = 0
                
            base_corr = max(10, current_corr - decrease)
            
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
        
        if actual_hit_index > 0:
            final_corr = final_corr - move.get('immediate_correction', 0)
            
        current_min_limit = max(1, int(10 * multiplier))
        min_limit_for_move = max(current_min_limit, move.get('minimum_guarantee', 0))
        final_corr = max(min_limit_for_move, final_corr)
        
        hit_damage = item.get('custom_damage', move['damage'])
        
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
        
        new_bonus = move.get('combo_correction', 0)
        if new_bonus > 0:
            next_reduction_bonus = new_bonus
            
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
        if actual_hit_index > 0:
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
                next_reduction_bonus = 0
                
            base_corr = max(10, current_corr - decrease)
            
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
        
        base_damage = item.get('custom_damage', move['damage'])
        
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
        
        if name == "SA2_1打目":
            sa2_saved_corr = final_corr
            
        new_bonus = move.get('combo_correction', 0)
        if new_bonus > 0:
            next_reduction_bonus = new_bonus
            
        actual_hit_index += 1
        if item.get('cdr', False):
            cdr_active = True
            
    return steps

# HTMLテンプレート (グリッドレイアウトによるカテゴリ整理)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>コンボ管理ノート ＆ 計算機</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        /* 数値入力のスピンボタン(上下矢印)を完全に排除して誤入力を防止 */
        .no-spin::-webkit-outer-spin-button,
        .no-spin::-webkit-inner-spin-button {
            -webkit-appearance: none;
            margin: 0;
        }
        .no-spin {
            -moz-appearance: textfield;
        }
    </style>
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
                    
                    <form id="combo-form" action="/add" method="post" class="space-y-4">
                        <input type="hidden" name="combo_id" id="combo-id">
                        <input type="hidden" name="moves_json" id="moves-json" value="[]">

                        <div>
                            <label class="block text-[11px] font-bold text-gray-600 mb-0.5">コンボ名・状況</label>
                            <input type="text" name="title" id="input-title" class="w-full px-3 py-1.5 border rounded-lg focus:ring-1 focus:ring-blue-500 text-sm" placeholder="例: 強Kパニカン" required>
                        </div>

                        <!-- 始動属性・使用リソースの設定 -->
                        <div class="grid grid-cols-3 gap-2">
                            <div>
                                <label class="block text-[11px] font-bold text-gray-600 mb-0.5">始動状態</label>
                                <select name="start_type" id="input-start-type" class="w-full px-2 py-1.5 border rounded-lg text-xs" onchange="updateLivePreview()">
                                    <option value="normal">通常ヒット</option>
                                    <option value="counter">カウンター (+2F)</option>
                                    <option value="punish">パニカン (+4F)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-[11px] font-bold text-gray-600 mb-0.5">使用可能ゲージ</label>
                                <select name="drive_start" id="input-drive-start" class="w-full px-2 py-1.5 border rounded-lg text-xs" onchange="updateLivePreview()">
                                    {% for g in range(6, -1, -1) %}
                                    <option value="{{ g }}">{{ g }}P</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div>
                                <label class="block text-[11px] font-bold text-gray-600 mb-0.5">使用可能シンボル</label>
                                <select name="symbol_start" id="input-symbol-start" class="w-full px-2 py-1.5 border rounded-lg text-xs" onchange="updateLivePreview()">
                                    {% for s in range(0, 5) %}
                                    <option value="{{ s }}">{{ s }}個</option>
                                    {% endfor %}
                                </select>
                            </div>
                        </div>

                        <!-- 技選択アコーディオンエリア (同系統がバラバラにならないようCSSグリッドで完全配置) -->
                        <div class="space-y-2">
                            <label class="block text-[11px] font-bold text-gray-600 mb-1">⚡ 技を追加する (クリックして開閉)</label>
                            
                            <!-- 通常技・特殊技 -->
                            <details class="border border-gray-200 rounded-lg bg-white overflow-hidden" open>
                                <summary class="px-3 py-2 bg-gray-50 text-xs font-bold text-gray-700 cursor-pointer hover:bg-gray-100 select-none flex justify-between items-center">
                                    <span>👊 通常技・特殊技</span>
                                    <span class="text-[10px] text-gray-400">クリックで開閉</span>
                                </summary>
                                <div class="p-3 space-y-3.5 bg-gray-50/50">
                                    <!-- 立ち攻撃 -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">■ 立ち通常技</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="弱P" onclick="addMove('弱P')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">弱P</button>
                                            <button type="button" data-move-name="弱K" onclick="addMove('弱K')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">弱K</button>
                                            <div class="hidden sm:block"></div>
                                            
                                            <button type="button" data-move-name="中Pタゲコン1" onclick="addMove('中Pタゲコン1')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition text-[11px] truncate">中Pタゲ1</button>
                                            <button type="button" data-move-name="中Pタゲコン2" onclick="addMove('中Pタゲコン2')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition text-[11px] truncate">中Pタゲ2</button>
                                            <button type="button" data-move-name="中K" onclick="addMove('中K')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">中K</button>
                                            
                                            <button type="button" data-move-name="強P" onclick="addMove('強P')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">強P</button>
                                            <button type="button" data-move-name="強K" onclick="addMove('強K')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">強K</button>
                                        </div>
                                    </div>

                                    <!-- しゃがみ攻撃 -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">■ しゃがみ通常技</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="屈弱P" onclick="addMove('屈弱P')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">屈弱P</button>
                                            <button type="button" data-move-name="屈弱K" onclick="addMove('屈弱K')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">屈弱K</button>
                                            <div class="hidden sm:block"></div>

                                            <button type="button" data-move-name="屈中P" onclick="addMove('屈中P')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">屈中P</button>
                                            <button type="button" data-move-name="屈中K" onclick="addMove('屈中K')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">屈中K</button>
                                            <div class="hidden sm:block"></div>

                                            <button type="button" data-move-name="屈強P" onclick="addMove('屈強P')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">屈強P</button>
                                            <button type="button" data-move-name="屈強K" onclick="addMove('屈強K')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">屈強K</button>
                                        </div>
                                    </div>

                                    <!-- 特殊技 ＆ ターゲットコンボ -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">■ 特殊技 ＆ 各種タゲコン</span>
                                        <div class="grid grid-cols-2 gap-1.5">
                                            <button type="button" data-move-name="中段" onclick="addMove('中段')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">中段</button>
                                            <button type="button" data-move-name="前強P" onclick="addMove('前強P')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-xs font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition">前強P</button>
                                            
                                            <button type="button" data-move-name="引中Kタゲコン1" onclick="addMove('引中Kタゲコン1')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-[11px] font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition truncate">引中Kタゲ1</button>
                                            <button type="button" data-move-name="引中Kタゲコン2" onclick="addMove('引中Kタゲコン2')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-[11px] font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition truncate">引中Kタゲ2</button>
                                            
                                            <button type="button" data-move-name="引強Pタゲコン1" onclick="addMove('引強Pタゲコン1')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-[11px] font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition truncate">引強Pタゲ1</button>
                                            <button type="button" data-move-name="引強Pタゲコン2" onclick="addMove('引強Pタゲコン2')" class="btn-move-add px-2 py-2 bg-white border border-gray-300 rounded text-[11px] font-semibold shadow-sm hover:bg-gray-50 active:scale-95 transition truncate">引強Pタゲ2</button>
                                        </div>
                                    </div>
                                </div>
                            </details>

                            <!-- システム・必殺技 -->
                            <details class="border border-gray-200 rounded-lg bg-white overflow-hidden" open>
                                <summary class="px-3 py-2 bg-gray-50 text-xs font-bold text-gray-700 cursor-pointer hover:bg-gray-100 select-none flex justify-between items-center">
                                    <span>🔥 システム ＆ 必殺技</span>
                                    <span class="text-[10px] text-gray-400">クリックで開閉</span>
                                </summary>
                                <div class="p-3 space-y-3.5 bg-gray-50/50">
                                    <!-- システム -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">🛠️ システムアクション</span>
                                        <div class="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="DR" onclick="addMove('DR')" class="btn-move-add px-2 py-2 bg-yellow-500 border border-yellow-600 text-white rounded text-xs font-bold hover:bg-yellow-600 active:scale-95 transition">DR(ラッシュ)</button>
                                            <button type="button" data-move-name="ドライブ回復1P" onclick="addMove('ドライブ回復1P')" class="btn-move-add px-2 py-2 bg-green-100 border border-green-300 text-green-800 rounded text-xs font-bold hover:bg-green-200 active:scale-95 transition">1P回復</button>
                                            <button type="button" data-move-name="インパクト" onclick="addMove('インパクト')" class="btn-move-add px-2 py-2 bg-yellow-100 border border-yellow-300 text-yellow-800 rounded text-xs font-bold hover:bg-yellow-200 active:scale-95 transition">インパクト</button>
                                            <button type="button" data-move-name="インパクト壁やられ" onclick="addMove('インパクト壁やられ')" class="btn-move-add px-2 py-2 bg-yellow-100 border border-yellow-300 text-yellow-800 rounded text-xs font-bold hover:bg-yellow-200 active:scale-95 transition">壁やられ</button>
                                            <button type="button" data-move-name="ジャストパリィ" onclick="addMove('ジャストパリィ')" class="btn-move-add px-2 py-2 bg-yellow-100 border border-yellow-300 text-yellow-800 rounded text-xs font-bold hover:bg-yellow-200 active:scale-95 transition">Jパリィ(始動)</button>
                                        </div>
                                    </div>

                                    <!-- サンシュート -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">☀️ サンシュート系</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="弱サンシュート" onclick="addMove('弱サンシュート')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">弱シュート</button>
                                            <button type="button" data-move-name="中サンシュート" onclick="addMove('中サンシュート')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">中シュート</button>
                                            <button type="button" data-move-name="強サンシュート" onclick="addMove('強サンシュート')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">強シュート</button>
                                            
                                            <button type="button" data-move-name="弱ODサンシュート" onclick="addMove('弱ODサンシュート')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">弱ODシュート</button>
                                            <button type="button" data-move-name="強ODサンシュート" onclick="addMove('強ODサンシュート')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">強ODシュート</button>
                                        </div>
                                    </div>

                                    <!-- サンライズ・サンパニッシュ -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">🌅 サンライズ ＆ サンパニッシュ</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="弱サンライズ" onclick="addMove('弱サンライズ')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">弱サンライズ</button>
                                            <button type="button" data-move-name="中サンライズ" onclick="addMove('中サンライズ')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">中サンライズ</button>
                                            <button type="button" data-move-name="強サンライズ" onclick="addMove('強サンライズ')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">強サンライズ</button>
                                            
                                            <button type="button" data-move-name="ODサンライズ" onclick="addMove('ODサンライズ')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">ODサンライズ</button>
                                            <button type="button" data-move-name="前サンパニッシュ" onclick="addMove('前サンパニッシュ')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition truncate">前サンパニ</button>
                                            <button type="button" data-move-name="上サンパニッシュ" onclick="addMove('上サンパニッシュ')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition truncate">上サンパニ</button>
                                        </div>
                                    </div>

                                    <!-- サンフレア -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">💥 サンフレア系 (設置)</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="弱サンフレア" onclick="addMove('弱サンフレア')" class="btn-move-add px-1 py-2 bg-red-100 border border-red-300 text-red-800 rounded text-[11px] font-black hover:bg-red-200 active:scale-95 transition col-span-3">弱サンフレア (シンボル+1)</button>
                                            <button type="button" data-move-name="Lv0サンフレア" onclick="addMove('Lv0サンフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv0フレア</button>
                                            <button type="button" data-move-name="Lv1サンフレア" onclick="addMove('Lv1サンフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv1フレア</button>
                                            <button type="button" data-move-name="Lv2サンフレア" onclick="addMove('Lv2サンフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv2フレア</button>
                                            <button type="button" data-move-name="Lv3サンフレア" onclick="addMove('Lv3サンフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv3フレア</button>
                                        </div>
                                    </div>

                                    <!-- ソーラーフレア -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">☄️ ソーラーフレア系</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="弱ソーラーフレア" onclick="addMove('弱ソーラーフレア')" class="btn-move-add px-1 py-2 bg-red-100 border border-red-300 text-red-800 rounded text-[11px] font-black hover:bg-red-200 active:scale-95 transition col-span-3">弱ソーラーフレア (シンボル+1)</button>
                                            <button type="button" data-move-name="Lv0ソーラーフレア" onclick="addMove('Lv0ソーラーフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv0ソーラー</button>
                                            <button type="button" data-move-name="Lv1ソーラーフレア" onclick="addMove('Lv1ソーラーフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv1ソーラー</button>
                                            <button type="button" data-move-name="Lv2ソーラーフレア" onclick="addMove('Lv2ソーラーフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv2ソーラー</button>
                                            <button type="button" data-move-name="Lv3ソーラーフレア" onclick="addMove('Lv3ソーラーフレア')" class="btn-move-add px-1 py-2 bg-red-50 border border-red-200 text-red-700 rounded text-[11px] font-bold hover:bg-red-100 active:scale-95 transition">Lv3ソーラー</button>
                                        </div>
                                    </div>
                                </div>
                            </details>

                            <!-- SA -->
                            <details class="border border-gray-200 rounded-lg bg-white overflow-hidden" open>
                                <summary class="px-3 py-2 bg-gray-50 text-xs font-bold text-gray-700 cursor-pointer hover:bg-gray-100 select-none flex justify-between items-center">
                                    <span>🔮 スーパーアーツ (SA)</span>
                                    <span class="text-[10px] text-gray-400">クリックで開閉</span>
                                </summary>
                                <div class="p-3 space-y-3.5 bg-gray-50/50">
                                    <!-- SA1 -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">■ SA1 (サンセイバー)</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="SA1_Lv0" onclick="addMove('SA1_Lv0')" class="btn-move-add px-1 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[11px] font-bold hover:bg-purple-100 active:scale-95 transition">SA1 Lv0</button>
                                            <button type="button" data-move-name="SA1_Lv1" onclick="addMove('SA1_Lv1')" class="btn-move-add px-1 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[11px] font-bold hover:bg-purple-100 active:scale-95 transition">SA1 Lv1</button>
                                            <button type="button" data-move-name="SA1_Lv2" onclick="addMove('SA1_Lv2')" class="btn-move-add px-1 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[11px] font-bold hover:bg-purple-100 active:scale-95 transition">SA1 Lv2</button>
                                        </div>
                                    </div>

                                    <!-- SA2発動 -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">■ SA2 発動演出 (ユーティリティ)</span>
                                        <div class="grid grid-cols-3 gap-1.5">
                                            <button type="button" data-move-name="SA2発動_Lv0" onclick="addMove('SA2発動_Lv0')" class="btn-move-add px-1 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[11px] font-bold hover:bg-purple-100 active:scale-95 transition">SA2発動 Lv0</button>
                                            <button type="button" data-move-name="SA2発動_Lv1" onclick="addMove('SA2発動_Lv1')" class="btn-move-add px-1 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[11px] font-bold hover:bg-purple-100 active:scale-95 transition">SA2発動 Lv1</button>
                                            <button type="button" data-move-name="SA2発動_Lv2" onclick="addMove('SA2発動_Lv2')" class="btn-move-add px-1 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[11px] font-bold hover:bg-purple-100 active:scale-95 transition">SA2発動 Lv2</button>
                                        </div>
                                    </div>

                                    <!-- SA2打撃 -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">■ SA2 分割ヒット打撃</span>
                                        <div class="grid grid-cols-5 gap-1">
                                            <button type="button" data-move-name="SA2_1打目" onclick="addMove('SA2_1打目')" class="btn-move-add px-0.5 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[10px] font-bold hover:bg-purple-100 active:scale-95 transition">1打目</button>
                                            <button type="button" data-move-name="SA2_2打目" onclick="addMove('SA2_2打目')" class="btn-move-add px-0.5 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[10px] font-bold hover:bg-purple-100 active:scale-95 transition">2打目</button>
                                            <button type="button" data-move-name="SA2_3打目" onclick="addMove('SA2_3打目')" class="btn-move-add px-0.5 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[10px] font-bold hover:bg-purple-100 active:scale-95 transition">3打目</button>
                                            <button type="button" data-move-name="SA2_4打目" onclick="addMove('SA2_4打目')" class="btn-move-add px-0.5 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[10px] font-bold hover:bg-purple-100 active:scale-95 transition">4打目</button>
                                            <button type="button" data-move-name="SA2_5打目" onclick="addMove('SA2_5打目')" class="btn-move-add px-0.5 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-[10px] font-bold hover:bg-purple-100 active:scale-95 transition">5打目</button>
                                        </div>
                                    </div>

                                    <!-- SA3/CA -->
                                    <div>
                                        <span class="text-[9px] font-bold text-gray-400 block mb-1">■ SA3 ＆ CA (アルティメット)</span>
                                        <div class="grid grid-cols-2 gap-1.5">
                                            <button type="button" data-move-name="SA3" onclick="addMove('SA3')" class="btn-move-add px-2 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-xs font-bold hover:bg-purple-100 active:scale-95 transition">SA3 (マキシマム)</button>
                                            <button type="button" data-move-name="CA" onclick="addMove('CA')" class="btn-move-add px-2 py-2 bg-purple-50 border border-purple-200 text-purple-700 rounded text-xs font-bold hover:bg-purple-100 active:scale-95 transition">CA (クリティカル)</button>
                                        </div>
                                    </div>
                                </div>
                            </details>
                        </div>

                        <!-- タイムライン -->
                        <div>
                            <label class="block text-[11px] font-bold text-gray-600 mb-1">➔ コンボタイムライン (直接数値を編集できます)</label>
                            <div id="timeline-container" class="border-2 border-dashed border-gray-200 rounded-xl p-3 bg-gray-50 min-h-[90px] flex flex-wrap gap-2 items-center">
                                <p id="timeline-placeholder" class="text-xs text-gray-400 w-full text-center py-5">レシピを構築してください</p>
                            </div>
                        </div>

                        <!-- リアルタイムプレビュー -->
                        <div class="bg-blue-50 border border-blue-100 rounded-lg p-3 flex justify-between items-center text-sm">
                            <div>
                                <span class="text-[9px] font-bold text-blue-500 block">合計ダメージ</span>
                                <span id="preview-damage" class="text-xl font-black text-blue-700">0</span>
                            </div>
                            <div class="text-right">
                                <span class="text-[9px] font-bold text-blue-500 block">リソース使用状況</span>
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
                            <button type="submit" id="submit-btn" class="flex-1 py-2.5 bg-blue-600 text-white text-xs font-bold rounded-lg hover:bg-blue-700 transition">コンボを登録</button>
                            <button type="button" id="cancel-btn" onclick="cancelEdit()" class="hidden px-4 py-2.5 bg-gray-200 text-gray-800 text-xs font-bold rounded-lg hover:bg-gray-300">中止</button>
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
                            {% for g in range(6, -1, -1) %}
                            <option value="{{ g }}" {% if drive_filter == g|string %}selected{% endif %}>使用可能ゲージ: {{ g }}P</option>
                            {% endfor %}
                        </select>
                        <select name="symbol_filter" class="px-2 py-1 border rounded text-xs">
                            <option value="all" {% if symbol_filter == 'all' or not symbol_filter %}selected{% endif %}>使用シンボル: すべて</option>
                            {% for s in range(0, 5) %}
                            <option value="{{ s }}" {% if symbol_filter == s|string %}selected{% endif %}>使用可能シンボル: {{ s }}個</option>
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
                        {% set drive_remain = combo.drive_start - combo.drive_cost %}
                        {% set symbol_remain = combo.symbol_start - combo.symbol_cost %}
                        {% set is_burnout_combo = (combo.drive_start == 6 and drive_remain <= 0) %}
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
                                <span class="px-2 py-0.5 text-xs font-bold rounded {{ 'bg-black text-yellow-400' if is_burnout_combo else 'bg-blue-100 text-blue-800' }}">
                                    🔵 使用ゲージ: {{ combo.drive_cost }}P (残り {{ drive_remain if drive_remain >= 0 else 0 }}P) {% if is_burnout_combo %}(バーンアウト！){% endif %}
                                </span>
                                <span class="px-2 py-0.5 bg-purple-100 text-purple-800 text-xs font-bold rounded">
                                    🔴 使用シンボル: {{ combo.symbol_cost }}個 (残り {{ symbol_remain if symbol_remain >= 0 else 0 }}個)
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

        function simulateResourcesSequentially(moves, startDrive, startSymbols) {
            let driveCurr = startDrive;
            let symbolCurr = startSymbols;
            let isInvalid = false;
            
            for (let i = 0; i < moves.length; i++) {
                const name = moves[i].name;
                const item = moves[i];
                
                if (name === "ドライブ回復1P") {
                    driveCurr = Math.min(6, driveCurr + 1);
                    continue;
                }
                if (name === "弱サンフレア" || name === "弱ソーラーフレア") {
                    symbolCurr = Math.min(4, symbolCurr + 1);
                    continue;
                }
                
                if (item.cdr) {
                    if (driveCurr <= 0) isInvalid = true;
                    driveCurr -= 3;
                }
                if (name === "DR") {
                    if (driveCurr <= 0) isInvalid = true;
                    driveCurr -= 1;
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
            const driveStart = parseInt(document.getElementById('input-drive-start').value) || 0;
            const symbolStart = parseInt(document.getElementById('input-symbol-start').value) || 0;

            // 編集中の入力フォーカス追跡処理
            const activeEl = document.activeElement;
            let focusedIndex = -1;
            if (activeEl && activeEl.classList.contains('damage-input')) {
                focusedIndex = parseInt(activeEl.getAttribute('data-index'));
            }

            let damage = 0;
            let currentCorr = 100;
            let cdrActive = false; 
            let nextReductionBonus = 0;
            let actualHitIndex = 0;
            let sa2SavedCorr = 100;

            const res = simulateResourcesSequentially(currentMoves, driveStart, symbolStart);
            const driveRemain = res.driveRemain;
            const symbolRemain = res.symbolRemain;

            const firstMoveName = currentMoves.length > 0 ? currentMoves[0].name : "";
            const impactWallActive = (firstMoveName === "インパクト壁やられ");
            const justParryActive = (firstMoveName === "ジャストパリィ");

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
                if (actualHitIndex > 0) {
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
                    
                    if (nextReductionBonus > 0 && actualHitIndex >= 2) {
                        if (actualHitIndex === 2) {
                            decrease = nextReductionBonus + (startCorrection > 0 ? 0 : 10);
                        } else {
                            decrease = nextReductionBonus;
                        }
                        nextReductionBonus = 0;
                    }

                    if (["SA2_2打目", "SA2_3打目", "SA2_4打目", "SA2_5打目"].includes(item.name)) {
                        decrease = 0;
                    }

                    baseCorr = Math.max(10, currentCorr - decrease);
                    
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

            const addButtons = document.querySelectorAll('.btn-move-add');
            addButtons.forEach(btn => {
                const moveName = btn.getAttribute('data-move-name');
                const move = MOVES_DB[moveName];
                if (!move) return;

                let isLocked = false;

                if ((moveName === "インパクト壁やられ" || moveName === "ジャストパリィ") && currentMoves.length > 0) {
                    isLocked = true;
                }

                // SA2打目ロック判定
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

                // === ターゲットコンボ（タゲコン2）のリアルタイム派生制限 ===
                if (moveName === "中Pタゲコン2") {
                    const lastMove = currentMoves.length > 0 ? currentMoves[currentMoves.length - 1] : null;
                    if (!lastMove || lastMove.name !== "中Pタゲコン1") {
                        isLocked = true;
                    }
                }
                if (moveName === "引中Kタゲコン2") {
                    const lastMove = currentMoves.length > 0 ? currentMoves[currentMoves.length - 1] : null;
                    if (!lastMove || lastMove.name !== "引中Kタゲコン1") {
                        isLocked = true;
                    }
                }
                if (moveName === "引強Pタゲコン2") {
                    const lastMove = currentMoves.length > 0 ? currentMoves[currentMoves.length - 1] : null;
                    if (!lastMove || lastMove.name !== "引強Pタゲコン1") {
                        isLocked = true;
                    }
                }

                // 順次シミュレーション
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

            document.getElementById('preview-damage').innerText = damage;
            
            // 使用量（消費量）の計算
            const driveCost = driveStart - driveRemain;
            const symbolCost = symbolStart - symbolRemain;
            
            let resourceText = `使用ゲージ: ${driveCost}P (残 ${Math.max(0, driveRemain)}P) | 🔴 使用シンボル: ${symbolCost}個 (残 ${Math.max(0, symbolRemain)}個)`;
            
            // ゲージが初期最大値「6P」から「0P（以下）」になった場合のみ、バーンアウト！を表記
            if (driveStart === 6 && driveRemain <= 0 && currentMoves.length > 0) {
                resourceText = `🔴 バーンアウト！ | 🔴 使用シンボル: ${symbolCost}個 (残 ${Math.max(0, symbolRemain)}個)`;
            }
            document.getElementById('preview-resources').innerText = resourceText;

            renderTimeline(driveRemain);
            document.getElementById('moves-json').value = JSON.stringify(currentMoves);

            // カーソルのフォーカス復元
            if (focusedIndex !== -1) {
                const nextInput = document.querySelector(`.damage-input[data-index="${focusedIndex}"]`);
                if (nextInput) {
                    nextInput.focus();
                    const tempVal = nextInput.value;
                    nextInput.value = '';
                    nextInput.value = tempVal;
                }
            }
        }

        function renderTimeline(driveRemain) {
            const container = document.getElementById('timeline-container');
            container.innerHTML = '';

            if (currentMoves.length === 0) {
                container.innerHTML = '<p id="timeline-placeholder" class="text-xs text-gray-400 w-full text-center py-5">レシピを構築してください</p>';
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
                block.className = `flex items-center gap-2 bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs font-bold shadow-sm transition-all ${
                    item.cdr ? 'bg-green-50 border-green-300 text-green-800' : 'text-gray-700'
                }`;

                let cdrBtn = '';
                if (canCDR) {
                    const isCdrLocked = !item.cdr && driveRemain <= 0;
                    const disabledAttr = isCdrLocked ? 'disabled title="ゲージ不足"' : '';
                    const opacityClass = isCdrLocked ? 'opacity-30 cursor-not-allowed' : 'hover:bg-gray-300';
                    
                    cdrBtn = `<button type="button" onclick="toggleCDR(${index})" ${disabledAttr} class="px-2 py-1 bg-gray-200 rounded text-[10px] ${opacityClass}">CDR</button>`;
                }

                const damageInputHTML = (item.name !== "DR" && item.name !== "インパクト壁やられ" && item.name !== "ジャストパリィ" && item.name !== "ドライブ回復1P" && item.name !== "弱サンフレア" && item.name !== "弱ソーラーフレア" && !item.name.startsWith("SA2発動")) 
                    ? `<div class="flex items-center gap-1 bg-gray-50 border border-gray-200 px-1.5 py-0.5 rounded ml-1">
                         <span class="text-[9px] text-gray-500 font-bold">単:</span>
                         <input type="number" data-index="${index}" oninput="updateCustomDamage(${index}, this.value)" class="damage-input w-16 h-6 px-1 py-0.5 border border-gray-300 rounded text-xs text-center font-bold bg-white focus:ring-1 focus:ring-blue-500 focus:border-blue-500 no-spin" value="${item.custom_damage}">
                       </div>`
                    : '';

                block.innerHTML = `
                    <span class="text-sm font-black text-gray-800">${item.name}</span>
                    ${damageInputHTML}
                    ${cdrBtn}
                    <button type="button" onclick="removeMove(${index})" class="text-red-500 font-black hover:text-red-700 ml-1.5 text-lg p-0.5">×</button>
                `;
                container.appendChild(block);
            });
        }

        function editCombo(id, title, startType, driveStart, symbolStart, notes, rawMovesJson) {
            document.getElementById('form-title').innerText = "📝 コンボを編集";
            document.getElementById('combo-id').value = id;
            document.getElementById('input-title').value = title;
            document.getElementById('input-start-type').value = startType;
            document.getElementById('input-drive-start').value = driveStart;
            document.getElementById('input-symbol-start').value = symbolStart;
            document.getElementById('input-notes').value = notes;

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

        // 初期ロード時実行
        window.addEventListener('DOMContentLoaded', () => {
            updateLivePreview();
        });
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
    if db_init_error:
        return f"""
        <div style="padding: 20px; font-family: sans-serif; background-color: #fff5f5; color: #c53030; border: 1px solid #feb2b2; border-radius: 8px; max-width: 800px; margin: 40px auto;">
            <h3 style="margin-top: 0;">⚠️ データベース接続エラーが発生しました</h3>
            <p>VercelからNeonデータベースへの接続設定、または接続処理中に以下の問題が発生しました：</p>
            <pre style="background: #fff; padding: 15px; border-radius: 4px; border: 1px solid #fed7d7; overflow-x: auto; font-family: monospace; font-size: 13px; color: #2d3748;">{db_init_error}</pre>
            <p style="font-size: 14px; color: #4a5568;">対策：Vercelの設定画面で「DATABASE_URL」環境変数が正しく登録されているか確認してください。</p>
        </div>
        """, 500

    drive_filter = request.args.get('drive_filter')
    symbol_filter = request.args.get('symbol_filter')
    search_query = request.args.get('search')
    
    # データベースから全レコードを取得
    try:
        combos_db = Combo.query.order_by(Combo.id.desc()).all()
    except Exception as e:
        combos_db = []
        print(f"Database error: {e}")

    combos = []
    for c in combos_db:
        combo_dict = {
            "id": c.id,
            "title": c.title,
            "start_type": c.start_type,
            "drive_start": c.drive_start,
            "drive_cost": c.drive_cost,
            "symbol_start": c.symbol_start,
            "symbol_cost": c.symbol_cost,
            "notes": c.notes,
            "moves": c.moves,
            "raw_moves_json": json.dumps(c.moves),
            "damage": c.damage
        }

        # フィルター処理
        if drive_filter and drive_filter != 'all':
            if combo_dict['drive_start'] != int(drive_filter):
                continue
        if symbol_filter and symbol_filter != 'all':
            if combo_dict['symbol_start'] != int(symbol_filter):
                continue
        if search_query:
            q = search_query.lower()
            in_title = q in combo_dict['title'].lower()
            in_notes = q in (combo_dict['notes'] or '').lower()
            if not (in_title or in_notes):
                continue
                
        # 画面描画用に動的な詳細ステップ計算をバインド
        combo_dict['steps'] = py_get_combo_details(combo_dict['moves'], combo_dict['start_type'])
        combos.append(combo_dict)
        
    return render_template_string(
        HTML_TEMPLATE, 
        combos=combos, 
        drive_filter=drive_filter, 
        symbol_filter=symbol_filter, 
        search_query=search_query,
        moves_db_json=json.dumps(MOVES_DB)
    )

@app.route('/add', methods=['POST'])
def add():
    moves = json.loads(request.form.get('moves_json', '[]'))
    start_type = request.form.get('start_type', 'normal')
    drive_start = int(request.form.get('drive_start', 6))
    symbol_start = int(request.form.get('symbol_start', 0))
    
    drive_remain, symbol_remain, _ = py_simulate_resources_sequentially(moves, drive_start, symbol_start)
    drive_cost = drive_start - drive_remain
    symbol_cost = symbol_start - symbol_remain
    damage = py_calculate_damage(moves, start_type)
    
    new_combo = Combo(
        id=str(int(time.time() * 1000)),
        title=request.form.get('title', '無題'),
        start_type=start_type,
        drive_start=drive_start,
        drive_cost=drive_cost,
        symbol_start=symbol_start,
        symbol_cost=symbol_cost,
        notes=request.form.get('notes', ''),
        moves=moves,
        damage=damage
    )
    
    try:
        db.session.add(new_combo)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Save error: {e}")
        
    return redirect(url_for('index'))

@app.route('/edit', methods=['POST'])
def edit():
    combo_id = request.form.get('combo_id')
    moves = json.loads(request.form.get('moves_json', '[]'))
    start_type = request.form.get('start_type', 'normal')
    drive_start = int(request.form.get('drive_start', 6))
    symbol_start = int(request.form.get('symbol_start', 0))
    
    drive_remain, symbol_remain, _ = py_simulate_resources_sequentially(moves, drive_start, symbol_start)
    drive_cost = drive_start - drive_remain
    symbol_cost = symbol_start - symbol_remain
    damage = py_calculate_damage(moves, start_type)
    
    combo = Combo.query.get(combo_id)
    if combo:
        combo.title = request.form.get('title', '無題')
        combo.start_type = start_type
        combo.drive_start = drive_start
        combo.drive_cost = drive_cost
        combo.symbol_start = symbol_start
        combo.symbol_cost = symbol_cost
        combo.notes = request.form.get('notes', '')
        combo.moves = moves
        combo.damage = damage
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Edit error: {e}")
            
    return redirect(url_for('index'))

@app.route('/delete/<combo_id>', methods=['POST'])
def delete(combo_id):
    combo = Combo.query.get(combo_id)
    if combo:
        try:
            db.session.delete(combo)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Delete error: {e}")
            
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)