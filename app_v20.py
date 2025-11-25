# app_v20.py
# Small iteration updated from v22: auto-advance, UI layout tidy, favorites & docx support merged into app_v20 file

import streamlit as st
import pandas as pd
import io
import re
import pickle
import os
import random
import time
import streamlit.components.v1 as components

# optional docx import
try:
    from docx import Document
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

st.set_page_config(page_title="ZenMode Ultimate v2.0.0 (iter v22)", layout="wide",
                   page_icon="🌙", initial_sidebar_state="expanded")

# --- CSS ---
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    [data-testid="stHeader"] { background-color: rgba(0,0,0,0); }
    footer {visibility: hidden;}
    .stApp { background-color: #000; color: #fff; }

    .hud-container { display:flex; justify-content:space-between; background:#111; padding:12px 18px; border-radius:10px; border:1px solid #222; margin-bottom:16px; align-items:center;}
    .hud-item { color:#cbd5e1; font-weight:600; }
    .hud-value { color:#ffffff; font-weight:800; margin-left:8px; }
    .hud-warn { color:#ff6b6b !important; }
    .hud-accent { color:#00ccff !important; }

    .zen-card { background:#0f1724; padding:22px; border-radius:12px; border:1px solid #1f2937; margin-bottom:14px; }
    .question-text { color:#fff; font-size:18px; font-weight:600; line-height:1.5; }

    .tag { display:inline-block; padding:4px 8px; background:#153A8B; color:#fff; border-radius:6px; font-weight:700; margin-bottom:8px; }

    .stRadio div[role='radiogroup'] > label {
        background:#0b1220; border:1px solid #263044; color:#ffffff !important;
        padding:12px 14px; border-radius:10px; margin-bottom:8px; font-size:15px !important; white-space: nowrap;
    }

    .stCheckbox label, .stCheckbox div, .stCheckbox { color: #FFFFFF !important; }
    .stCheckbox input[type="checkbox"] { accent-color: #00ccff; }
    div[data-baseweb="checkbox"] label { color: #FFFFFF !important; }

    button[kind="primary"] { background-color:#0066FF !important; color:#fff !important; border-radius:10px; height:44px; white-space:nowrap; padding:0 18px; }
    .stButton>button{white-space:nowrap;}

    .feedback-box { padding:10px; border-radius:8px; margin:10px 0; text-align:center; font-weight:700; }
    .feedback-success { background:#063; color:#8ef7bf; border:1px solid #059669; }
    .feedback-error { background:#4b0b0b; color:#ffc1c1; border:1px solid #b91c1c; }

    .small-meta { color:#9ca3af; font-size:13px; }
</style>
""", unsafe_allow_html=True)

# --- regex & parsing helpers (same approach as v21) ---
RE_OPTS_1 = re.compile(r'(^|\s)([A-Z])[.、\)]:：]\s*(.*?)(?=\s+[A-Z][.、\)]:：]|$)', re.DOTALL | re.MULTILINE)
RE_OPTS_2 = re.compile(r'(^|\s)\(?([A-Z])\)[.、\)]:：]?\s*(.*?)(?=\s+\(?[A-Z]\)?[.、\)]:：]?|$)', re.DOTALL | re.MULTILINE)
RE_OPTS_3 = re.compile(r'([A-Z])[.、\)]:：](.*?)(?=[A-Z][.、\)]:：]|$)', re.DOTALL | re.MULTILINE)
RE_ANSWER = re.compile(r'(答案|answer|正确答案|answer:|answer：)\s*[:：]?\s*([A-Z对错TrueFalseABCD]+)', re.IGNORECASE)
RE_ANSWER_SIMPLE = re.compile(r'^[\s]*(A|B|C|D|A\.|B\.|C\.|D\.|对|错)\s*$', re.IGNORECASE | re.MULTILINE)

def normalize_text(text):
    if text is None: return ""
    return str(text).strip()

def parse_options_from_text(text):
    text = normalize_text(text)
    options = {}
    question_text = text
    for idx, p in enumerate([RE_OPTS_1, RE_OPTS_2, RE_OPTS_3]):
        matches = list(p.finditer(text))
        if len(matches) >= 2:
            temp = {}
            first_pos = float('inf')
            for m in matches:
                if idx == 2:
                    key, val = m.group(1).upper(), m.group(2).strip()
                else:
                    groups = m.groups()
                    key, val = groups[-2].upper(), groups[-1].strip()
                temp[key] = val
                if m.start() < first_pos:
                    first_pos = m.start()
            if temp:
                return text[:first_pos].strip(), temp
    return question_text, options

def extract_answer_from_text(text):
    if not text: return ""
    m = RE_ANSWER.search(text)
    if m:
        ans_raw = m.group(2).strip()
        if ans_raw in ["对", "True", "true"]: return "A"
        if ans_raw in ["错", "False", "false"]: return "B"
        mm = re.search(r'[A-Z]', ans_raw.upper())
        if mm:
            return mm.group(0)
        return ans_raw.upper()
    mm = RE_ANSWER_SIMPLE.search(text)
    if mm:
        token = mm.group(1)
        if token in ["对", "True", "true"]: return "A"
        if token in ["错", "False", "false"]: return "B"
        return token.replace('.', '').upper()
    return ""

# --- Excel / DOCX parsing (cached for excel) ---
@st.cache_data(ttl=60*60, show_spinner=False)
def parse_excel_bytes(file_bytes):
    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as e:
        raise RuntimeError(f"读取 Excel 失败: {e}")
    df.columns = [str(c).strip() for c in df.columns]

    def find_col(cols, kws):
        for c in cols:
            for kw in kws:
                if kw in c: return c
        return None

    col_type = find_col(df.columns, ['类型', 'Type', '题型'])
    col_content = find_col(df.columns, ['内容', 'Content', '题目'])
    col_answer = find_col(df.columns, ['答案', 'Answer', '结果'])
    if not (col_type and col_content and col_answer):
        raise RuntimeError("Excel 缺少必要列 (需包含: 类型, 内容, 答案)")

    df[col_type] = df[col_type].fillna("").astype(str)
    df[col_content] = df[col_content].fillna("").astype(str)
    df[col_answer] = df[col_answer].fillna("").astype(str)

    records = df.to_dict('records')
    questions = []
    for i, row in enumerate(records):
        raw_type = normalize_text(row[col_type]).upper()
        raw_content = row[col_content]
        raw_answer = normalize_text(row[col_answer]).upper()
        if any(x in raw_type for x in ['AO', '判断']): q_code, q_name = 'AO', '判断题'
        elif any(x in raw_type for x in ['BO', '单选']): q_code, q_name = 'BO', '单选题'
        elif any(x in raw_type for x in ['CO', '多选']): q_code, q_name = 'CO', '多选题'
        else: q_code, q_name = 'UNK', '未知'
        q_text, q_options = parse_options_from_text(raw_content)
        if q_code in ['BO', 'CO'] and not q_options: q_options = {}
        questions.append({
            "id": i, "code": q_code, "type": q_name,
            "content": q_text, "options": q_options, "answer": raw_answer,
            "user_answer": None, "raw_content": raw_content
        })
    return questions

def parse_docx_bytes(file_bytes):
    if not DOCX_AVAILABLE:
        raise RuntimeError("docx 解析依赖缺失，请安装 python-docx (pip install python-docx)")
    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as e:
        raise RuntimeError(f"读取 docx 失败: {e}")
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    blocks, current = [], []
    for t in paras:
        if re.match(r'^\d+[\.、\)]', t) or re.match(r'^(题|Q|Question)', t, re.IGNORECASE):
            if current: blocks.append("\n".join(current))
            current = [t]
        else:
            current.append(t)
    if current: blocks.append("\n".join(current))
    questions = []
    for i, b in enumerate(blocks):
        ans = extract_answer_from_text(b)
        q_text, q_options = parse_options_from_text(b)
        if '判断' in b or re.search(r'对|错|True|False', b, re.IGNORECASE):
            q_code, q_name = 'AO', '判断题'
        elif q_options:
            if re.search(r'多选', b) or (ans and len(ans) > 1):
                q_code, q_name = 'CO', '多选题'
            else:
                q_code, q_name = 'BO', '单选题'
        else:
            q_code, q_name = 'UNK', '未知'
        questions.append({
            "id": i, "code": q_code, "type": q_name,
            "content": q_text, "options": q_options, "answer": ans,
            "user_answer": None, "raw_content": b
        })
    return questions

# --- state persistence ---
DATA_FILE = "user_data_v22.pkl"
def save_state():
    state = {
        "banks": st.session_state.banks,
        "progress": st.session_state.progress,
        "active_bank": st.session_state.active_bank,
        "filters": st.session_state.filters,
        "favorites": st.session_state.favorites
    }
    try:
        with open(DATA_FILE, "wb") as f:
            pickle.dump(state, f)
    except Exception:
        pass

def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "rb") as f:
                state = pickle.load(f)
                st.session_state.banks = state.get("banks", {})
                st.session_state.progress = state.get("progress", {})
                st.session_state.active_bank = state.get("active_bank", None)
                st.session_state.filters = state.get("filters", {})
                st.session_state.favorites = state.get("favorites", [])
                return True
        except Exception:
            pass
    return False

# --- init session_state ---
if 'init' not in st.session_state:
    st.session_state.banks = {}
    st.session_state.progress = {}
    st.session_state.active_bank = None
    st.session_state.filters = {}
    st.session_state.favorites = []
    st.session_state.show_fav = False
    load_state()
    st.session_state.init = True

# --- handle client reload auto-advance param ---
params = st.experimental_get_query_params()
if params.get("advance") and st.session_state.get("pending_advance") is not None and st.session_state.active_bank:
    # perform advance once
    bk_adv = st.session_state.active_bank
    pg = st.session_state.progress.setdefault(bk_adv, {"history": {}, "wrong": [], "current_idx": 0})
    pg["current_idx"] = st.session_state.pending_advance
    # clean-up
    st.session_state.pending_advance = None
    save_state()
    # clear params and rerun to show next question
    st.experimental_set_query_params()
    st.experimental_rerun()

# --- Sidebar ---
with st.sidebar:
    st.header("🛠️ 控制台")
    st.subheader("📚 题库")
    bank_names = list(st.session_state.banks.keys())

    if bank_names:
        curr_idx = bank_names.index(st.session_state.active_bank) if st.session_state.active_bank in bank_names else 0
        selected = st.selectbox("切换题库", bank_names, index=curr_idx)
        if selected != st.session_state.active_bank:
            st.session_state.active_bank = selected
            st.session_state.progress.setdefault(selected, {"history": {}, "wrong": [], "current_idx": 0})
            st.session_state.filters.setdefault(selected, list({q['type'] for q in st.session_state.banks.get(selected, [])}))
            save_state()
            st.rerun()

        curr_q_list = st.session_state.banks.get(st.session_state.active_bank, [])
        all_types = list({q['type'] for q in curr_q_list}) if curr_q_list else []
        default_sel = st.session_state.filters.get(st.session_state.active_bank, all_types)
        st.markdown("---")
        st.subheader("🎯 题型筛选")
        selected_types = st.multiselect("只刷这些题型：", all_types, default=default_sel)
        if selected_types != default_sel:
            st.session_state.filters[st.session_state.active_bank] = selected_types
            st.session_state.progress.setdefault(st.session_state.active_bank, {"history": {}, "wrong": [], "current_idx": 0})
            st.session_state.progress[st.session_state.active_bank]["current_idx"] = 0
            save_state()
            st.rerun()

        st.markdown("---")
        if st.button("🔀 随机抽取 100 题（基于筛选）", use_container_width=True):
            filtered = [q for q in curr_q_list if q['type'] in selected_types]
            if not filtered:
                st.warning("当前筛选下没有题目，无法抽题。")
            else:
                sample_n = min(100, len(filtered))
                sampled = random.sample(filtered, sample_n)
                tmp_name = f"{st.session_state.active_bank}_随机{sample_n}"
                st.session_state.banks[tmp_name] = [{**q, "user_answer": None} for q in sampled]
                st.session_state.progress[tmp_name] = {"history": {}, "wrong": [], "current_idx": 0}
                st.session_state.filters[tmp_name] = list({q['type'] for q in sampled})
                st.session_state.active_bank = tmp_name
                save_state()
                st.success(f"已创建题库：{tmp_name}，共 {sample_n} 题，已开始练习。")
                st.rerun()
    else:
        st.info("暂无题库，先导入一个 Excel 或 Word 文档。")

    # Favorites
    st.markdown("---")
    st.subheader("⭐ 收藏题目")
    fav_count = len(st.session_state.favorites)
    st.write(f"已收藏 {fav_count} 道题")
    if fav_count > 0:
        if st.button("查看收藏列表", use_container_width=True):
            st.session_state.show_fav = True
        if st.button("导出收藏 (可再次导入)", use_container_width=True):
            rows = []
            for q in st.session_state.favorites:
                rows.append({
                    "题目类型": q.get("type", ""),
                    "题目内容": q.get("raw_content", q.get("content", "")),
                    "正确答案": q.get("answer", ""),
                    "你的误选": q.get("user_answer", "")
                })
            df = pd.DataFrame(rows)
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.download_button("下载收藏.xlsx", out.getvalue(), "收藏题目.xlsx", use_container_width=True)
        if st.button("保存收藏为题库", use_container_width=True):
            new_name = "收藏题库"
            if new_name in st.session_state.banks:
                new_name += f"_{int(random.random()*10000)}"
            new_qs = [{**q, "user_answer": None} for q in st.session_state.favorites]
            st.session_state.banks[new_name] = new_qs
            st.session_state.progress[new_name] = {"history": {}, "wrong": [], "current_idx": 0}
            st.session_state.filters[new_name] = list({q['type'] for q in new_qs})
            st.session_state.active_bank = new_name
            save_state()
            st.success(f"已创建题库：{new_name}，并切换到该题库。")
            st.rerun()

    if fav_count > 0 and st.button("清空收藏", use_container_width=True):
        st.session_state.favorites = []
        save_state()
        st.success("已清空收藏。")
        st.rerun()

    st.markdown("---")
    # Import area
    st.subheader("➕ 导入题库")
    uploaded_excel = st.file_uploader("上传 Excel (.xlsx/.xls)", type=["xlsx", "xls"])
    uploaded_docx = st.file_uploader("上传 Word (.docx)", type=["docx"])
    name_input = st.text_input("题库命名（可选）", key="import_name")
    if uploaded_excel and st.button("导入 Excel", use_container_width=True):
        file_bytes = uploaded_excel.getvalue()
        try:
            with st.spinner("解析 Excel..."):
                qs = parse_excel_bytes(file_bytes)
        except Exception as e:
            st.error(f"导入失败：{e}")
        else:
            final_name = name_input.strip() if name_input.strip() else uploaded_excel.name.split(".")[0]
            if final_name in st.session_state.banks:
                final_name += f"_{int(random.random()*100000)}"
            st.session_state.banks[final_name] = qs
            st.session_state.progress[final_name] = {"history": {}, "wrong": [], "current_idx": 0}
            st.session_state.filters[final_name] = list({q['type'] for q in qs})
            st.session_state.active_bank = final_name
            save_state()
            st.success(f"已导入题库：{final_name} （共 {len(qs)} 题）")
            st.rerun()

    if uploaded_docx and st.button("导入 Word (.docx)", use_container_width=True):
        file_bytes = uploaded_docx.getvalue()
        try:
            with st.spinner("解析 Word 文档..."):
                qs = parse_docx_bytes(file_bytes)
        except Exception as e:
            st.error(f"导入失败：{e}")
            if not DOCX_AVAILABLE:
                st.info("提示：请在运行环境安装 python-docx：pip install python-docx")
        else:
            final_name = name_input.strip() if name_input.strip() else uploaded_docx.name.split(".")[0]
            if final_name in st.session_state.banks:
                final_name += f"_{int(random.random()*100000)}"
            st.session_state.banks[final_name] = qs
            st.session_state.progress[final_name] = {"history": {}, "wrong": [], "current_idx": 0}
            st.session_state.filters[final_name] = list({q['type'] for q in qs})
            st.session_state.active_bank = final_name
            save_state()
            st.success(f"已导入 Word 题库：{final_name} （共 {len(qs)} 题）")
            st.rerun()

    # Delete bank
    if st.session_state.active_bank:
        st.markdown("---")
        with st.expander("⚠️ 删除当前题库"):
            if st.button("确认删除当前题库", use_container_width=True):
                name_del = st.session_state.active_bank
                if name_del in st.session_state.banks: del st.session_state.banks[name_del]
                if name_del in st.session_state.progress: del st.session_state.progress[name_del]
                if name_del in st.session_state.filters: del st.session_state.filters[name_del]
                st.session_state.active_bank = list(st.session_state.banks.keys())[0] if st.session_state.banks else None
                save_state()
                st.success("已删除题库。")
                st.rerun()

# --- show favorites modal if requested ---
if st.session_state.get("show_fav", False):
    st.markdown("### ⭐ 收藏题目列表")
    for i, q in enumerate(list(st.session_state.favorites)):
        st.markdown(f"**{i+1}. [{q.get('type')}]** {q.get('content')}")
        cols = st.columns([1,1,1])
        if cols[0].button("取消收藏", key=f"unfav_{i}"):
            st.session_state.favorites = [f for f in st.session_state.favorites if f.get("raw_content") != q.get("raw_content")]
            save_state()
            st.experimental_rerun()
        if cols[1].button("导出此题", key=f"export_fav_{i}"):
            df = pd.DataFrame([{ "题目类型": q.get("type",""), "题目内容": q.get("raw_content", q.get("content","")), "正确答案": q.get("answer",""), "你的误选": q.get("user_answer","") }])
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False)
            st.download_button("下载", out.getvalue(), f"fav_{i+1}.xlsx")
        if cols[2].button("存为题库", key=f"fav2bank_{i}"):
            new_name = f"fav_{int(random.random()*100000)}"
            st.session_state.banks[new_name] = [{**qq, "user_answer": None} for qq in st.session_state.favorites]
            st.session_state.progress[new_name] = {"history": {}, "wrong": [], "current_idx": 0}
            st.session_state.filters[new_name] = list({qq['type'] for qq in st.session_state.banks[new_name]})
            st.session_state.active_bank = new_name
            save_state()
            st.success(f"已创建题库：{new_name}")
            st.experimental_rerun()
    if st.button("关闭收藏列表"):
        st.session_state.show_fav = False
        st.experimental_rerun()

# --- Main quiz area ---
if not st.session_state.active_bank:
    st.markdown("<div style='text-align:center; padding:60px 0;'><h1>👋 ZenMode Ultimate</h1><p class='small-meta'>请在侧边栏导入或选择题库</p></div>", unsafe_allow_html=True)
else:
    bk = st.session_state.active_bank
    full_qs = st.session_state.banks.get(bk, [])
    active_filters = st.session_state.filters.get(bk, list({q['type'] for q in full_qs}))
    if not active_filters:
        active_filters = list({q['type'] for q in full_qs})
        st.session_state.filters[bk] = active_filters

    qs = [q for q in full_qs if q['type'] in active_filters]
    pg = st.session_state.progress.setdefault(bk, {"history": {}, "wrong": [], "current_idx": 0})
    idx = pg.get("current_idx", 0)
    if idx > len(qs):
        idx = len(qs)
        pg["current_idx"] = idx

    total_q = len(qs)
    done_q = min(idx + 1, total_q)
    wrong_q = len(pg.get("wrong", []))

    st.markdown(f"""
    <div class="hud-container">
        <div>
            <div class="hud-item">题库: <span class="hud-value">{bk}</span></div>
            <div class="small-meta">筛选：{', '.join(active_filters)}</div>
        </div>
        <div style="text-align:right;">
            <div class="hud-item">进度 <span class="hud-value hud-accent">{done_q}</span>/<span class="small-meta">{total_q}</span></div>
            <div class="hud-item">错题 <span class="hud-value hud-warn">{wrong_q}</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if total_q == 0:
        st.warning("当前筛选下没有题目，请在侧边栏调整筛选或导入题库。")
    elif idx >= total_q:
        st.markdown(f"<div style='text-align:center; padding:20px; background:#071223; border-radius:10px;'><h3>🎉 练习完成</h3><p class='small-meta'>共 {total_q} 题，错题 {wrong_q} 道</p></div>", unsafe_allow_html=True)
        if st.button("🔁 再刷一次", use_container_width=True, type="primary"):
            pg["current_idx"] = 0
            pg["history"] = {}
            save_state()
            st.rerun()
    else:
        q = qs[idx]
        st.markdown(f"""<div class="zen-card"><span class="tag">{q.get('type')}</span><div class="question-text">{q.get('content')}</div></div>""", unsafe_allow_html=True)

        # favorite controls (compact, unique keys)
        fav_c1, fav_c2 = st.columns([1,3])
        if fav_c1.button("⭐ 收藏", key=f"fav_add_{bk}_{idx}", use_container_width=True):
            if not any(fav.get("raw_content") == q.get("raw_content") for fav in st.session_state.favorites):
                ff = q.copy(); ff["user_answer"] = ff.get("user_answer", None)
                st.session_state.favorites.append(ff); save_state(); st.success("已加入收藏"); st.experimental_rerun()
            else:
                st.info("此题已收藏")
        if fav_c2.button("🔖 取消收藏", key=f"fav_rem_{bk}_{idx}", use_container_width=True):
            before = len(st.session_state.favorites)
            st.session_state.favorites = [f for f in st.session_state.favorites if f.get("raw_content") != q.get("raw_content")]
            if len(st.session_state.favorites) < before:
                save_state(); st.success("已取消收藏")
            else:
                st.info("该题尚未收藏")

        # answer input
        user_choice = None
        saved = pg["history"].get(idx)
        if q.get("code") == "AO":
            sel_idx = 0 if saved == "A" else (1 if saved == "B" else 0)
            val = st.radio("判断:", ["A", "B"], index=sel_idx, format_func=lambda x: "✅ 正确" if x=='A' else "❌ 错误", horizontal=True, key=f"ans_{bk}_{idx}")
            user_choice = val
        elif q.get("code") == "BO":
            if q.get("options"):
                keys = list(q["options"].keys()); disp = [f"{k}. {v}" for k,v in q["options"].items()]
                sel_idx = keys.index(saved) if saved in keys else 0
                val = st.radio("选择:", disp, index=sel_idx, key=f"ans_{bk}_{idx}")
                user_choice = val.split(".")[0] if val else None
            else:
                user_choice = st.text_input("答案：", value=saved or "", key=f"ans_{bk}_{idx}_text").strip().upper()
        elif q.get("code") == "CO":
            st.write("多项选择：")
            if q.get("options"):
                sel_list = []
                for k,v in q["options"].items():
                    checked = (k in saved) if saved else False
                    if st.checkbox(f"{k}. {v}", value=checked, key=f"ans_{bk}_{idx}_{k}"):
                        sel_list.append(k)
                user_choice = "".join(sorted(sel_list)) if sel_list else ""
            else:
                user_choice = st.text_input("答案：", value=saved or "", key=f"ans_{bk}_{idx}_text").strip().upper()
        else:
            user_choice = st.text_input("答案（自由）：", value=saved or "", key=f"ans_{bk}_{idx}_text").strip()

        # controls and feedback placeholder
        feedback = st.empty()
        c1, c2, c3 = st.columns([1,2,1])
        if c1.button("⬅ 上一题", disabled=(idx==0), key=f"prev_{bk}_{idx}", use_container_width=True):
            pg["current_idx"] = max(0, idx-1); save_state(); st.rerun()

        if c2.button("提交", type="primary", key=f"submit_{bk}_{idx}", use_container_width=True):
            if user_choice is None or (isinstance(user_choice, str) and user_choice.strip() == ""):
                st.warning("请先作答")
            else:
                # record answer
                pg["history"][idx] = user_choice
                ans = q.get("answer", "")
                if q.get("code") == "AO":
                    if ans == "对": ans = "A"
                    if ans == "错": ans = "B"
                is_correct = (user_choice == ans)
                if is_correct:
                    feedback.markdown(f"""<div class="feedback-box feedback-success">✅ 回答正确！</div>""", unsafe_allow_html=True)
                else:
                    feedback.markdown(f"""<div class="feedback-box feedback-error">❌ 回答错误。正确答案：<strong>{q.get('answer','')}</strong></div>""", unsafe_allow_html=True)
                    if not any(w.get("raw_content") == q.get("raw_content") for w in pg.get("wrong", [])):
                        qc = q.copy(); qc["user_answer"] = user_choice; pg.setdefault("wrong", []).append(qc)
                save_state()
                # set pending advance and trigger client reload with param after short delay (JS)
                st.session_state.pending_advance = idx + 1
                components.html(f"<script>setTimeout(()=>{{let u=location.pathname + '?advance=1'; location.href=u;}},900);</script>", height=0)

        if c3.button("跳过 ➡", key=f"skip_{bk}_{idx}", use_container_width=True):
            pg["current_idx"] = idx + 1; save_state(); st.rerun()
