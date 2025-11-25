import streamlit as st
import pandas as pd
import io
import re
import time
import pickle
import os
import random

# --- 配置（请确保这是文件开头的第一段 Streamlit 配置） ---
st.set_page_config(
    page_title="ZenMode Ultimate",
    layout="wide",
    page_icon="🌙",
    initial_sidebar_state="expanded"
)

# --- 样式：暗色、高对比、修复多选颜色问题 ---
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    [data-testid="stHeader"] { background-color: rgba(0,0,0,0); }
    footer {visibility: hidden;}
    .stApp { background-color: #000000; color: #FFFFFF; }

    /* HUD */
    .hud-container { display:flex; justify-content:space-between; background:#111; padding:12px 18px; border-radius:10px; border:1px solid #222; margin-bottom:18px; align-items:center;}
    .hud-item { color:#cbd5e1; font-weight:600; }
    .hud-value { color:#ffffff; font-weight:800; margin-left:8px; }
    .hud-warn { color:#ff6b6b !important; }
    .hud-accent { color:#00ccff !important; }

    /* 卡片 */
    .zen-card { background:#0f1724; padding:28px; border-radius:14px; border:1px solid #1f2937; margin-bottom:18px; }
    .question-text { color:#fff; font-size:20px; font-weight:600; line-height:1.5; }

    .tag { display:inline-block; padding:4px 10px; background:#153A8B; color:#fff; border-radius:6px; font-weight:700; }

    /* 单选项 */
    .stRadio div[role='radiogroup'] > label {
        background:#0b1220; border:1px solid #263044; color:#ffffff !important;
        padding:14px 16px; border-radius:10px; margin-bottom:10px; font-size:16px !important;
    }
    .stRadio div[role='radiogroup'] > label:hover {
        background:#16202b; border-color:#00ccff; color:#fff !important;
    }

    /* 复选（多选）修正：文字显色 */
    .stCheckbox label, .stCheckbox div, .stCheckbox { color: #FFFFFF !important; }
    .stCheckbox input[type="checkbox"] { accent-color: #00ccff; }
    /* 兼容多种 Streamlit 版本，尽量强制设置 checkbox label */
    div[data-baseweb="checkbox"] label { color: #FFFFFF !important; }

    /* 多选下拉/多选列表文字 */
    .stMultiSelect label, .stSelectbox label { color:#FFFFFF !important; }

    /* 按钮 */
    button[kind="primary"] { background-color:#0066FF !important; color:#fff !important; border-radius:10px; height:48px; }

    /* 反馈 */
    .feedback-box { padding:12px; border-radius:8px; margin:12px 0; text-align:center; font-weight:700; }
    .feedback-success { background:#063; color:#8ef7bf; border:1px solid #059669; }
    .feedback-error { background:#4b0b0b; color:#ffc1c1; border:1px solid #b91c1c; }

    .small-meta { color:#9ca3af; font-size:13px; }
</style>
""", unsafe_allow_html=True)

DATA_FILE = "user_data_v19.pkl"

# --- 性能优化：预编译正则 ---
RE_OPTS_1 = re.compile(r'(^|\s)([A-Z])[.、:．]\s*(.*?)(?=\s+[A-Z][.、:．]|$)', re.DOTALL | re.MULTILINE)
RE_OPTS_2 = re.compile(r'(^|\s)\(?([A-Z])\)[.:]?\s*(.*?)(?=\s+\(?[A-Z]\)?[.:]?|$)', re.DOTALL | re.MULTILINE)
RE_OPTS_3 = re.compile(r'([A-Z])[.、:．](.*?)(?=[A-Z][.、:．]|$)', re.DOTALL | re.MULTILINE)

# --- 解析函数：缓存二进制文件解析结果，加速重复导入 ---
@st.cache_data(ttl=60*60, show_spinner=False)  # 缓存 1 小时
def parse_excel_bytes(file_bytes):
    """
    接受 file_bytes (bytes)，返回 questions 列表。
    这是不依赖 Streamlit UI 的纯计算函数，适合缓存。
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
        df.columns = [str(c).strip() for c in df.columns]
    except Exception as e:
        raise RuntimeError(f"读取 Excel 失败: {e}")

    # 查找列
    def find_col_local(cols, kws):
        for c in cols:
            for kw in kws:
                if kw in c:
                    return c
        return None

    col_type = find_col_local(df.columns, ['类型', 'Type', '题型'])
    col_content = find_col_local(df.columns, ['内容', 'Content', '题目'])
    col_answer = find_col_local(df.columns, ['答案', 'Answer', '结果'])
    if not (col_type and col_content and col_answer):
        raise RuntimeError("Excel 缺少必要列 (需包含: 类型, 内容, 答案)")

    # 预处理列
    df[col_type] = df[col_type].fillna("").astype(str)
    df[col_content] = df[col_content].fillna("").astype(str)
    df[col_answer] = df[col_answer].fillna("").astype(str)

    records = df.to_dict('records')
    questions = []

    for i, row in enumerate(records):
        raw_type = str(row[col_type]).strip().upper()
        raw_content = row[col_content]
        raw_answer = str(row[col_answer]).strip().upper()

        if any(x in raw_type for x in ['AO', '判断']): q_code, q_name = 'AO', '判断题'
        elif any(x in raw_type for x in ['BO', '单选']): q_code, q_name = 'BO', '单选题'
        elif any(x in raw_type for x in ['CO', '多选']): q_code, q_name = 'CO', '多选题'
        else: q_code, q_name = 'UNK', '未知'

        # 解析选项（返回 content 与 options dict）
        q_text, q_options = parse_options_zen_local(raw_content)

        if q_code in ['BO', 'CO'] and not q_options:
            q_options = {}

        questions.append({
            "id": i,
            "code": q_code,
            "type": q_name,
            "content": q_text,
            "options": q_options,
            "answer": raw_answer,
            "user_answer": None,
            "raw_content": raw_content
        })

    return questions

def parse_options_zen_local(text):
    text = "" if text is None else str(text).strip()
    options = {}
    question_text = text

    patterns = [RE_OPTS_1, RE_OPTS_2, RE_OPTS_3]
    for idx, p in enumerate(patterns):
        matches = list(p.finditer(text))
        if len(matches) >= 2:
            temp_options = {}
            first_match_start = float('inf')
            for m in matches:
                if idx == 2:
                    key, val = m.group(1).upper(), m.group(2).strip()
                else:
                    groups = m.groups()
                    key, val = groups[-2].upper(), groups[-1].strip()
                temp_options[key] = val
                if m.start() < first_match_start: first_match_start = m.start()
            if temp_options:
                return text[:first_match_start].strip(), temp_options
    return question_text, options

# --- 状态持久化 ---
def save_state():
    state = {
        "banks": st.session_state.banks,
        "progress": st.session_state.progress,
        "active_bank": st.session_state.active_bank,
        "filters": st.session_state.filters
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
                return True
        except Exception:
            pass
    return False

# --- init ---
if 'init' not in st.session_state:
    st.session_state.banks = {}
    st.session_state.progress = {}
    st.session_state.active_bank = None
    st.session_state.filters = {}
    # 计时相关
    st.session_state.overall_start_time = None  # 整个练习队列开始时间（epoch）
    st.session_state.q_start_time = None        # 当前题开始时间（epoch）
    load_state()
    st.session_state.init = True

# --- 侧边栏（控制台） ---
with st.sidebar:
    st.header("🛠️ 控制台")
    st.subheader("📚 题库")
    bank_names = list(st.session_state.banks.keys())

    if bank_names:
        curr_idx = bank_names.index(st.session_state.active_bank) if st.session_state.active_bank in bank_names else 0
        selected = st.selectbox("切换题库", bank_names, index=curr_idx)
        if selected != st.session_state.active_bank:
            st.session_state.active_bank = selected
            # 切换题库时重置每题计时（会在主界面重新设置）
            st.session_state.q_start_time = None
            save_state()
            st.rerun()

        # 题型筛选
        curr_q_list = st.session_state.banks.get(st.session_state.active_bank, [])
        all_types = list({q['type'] for q in curr_q_list}) if curr_q_list else []
        default_sel = st.session_state.filters.get(st.session_state.active_bank, all_types)
        st.markdown("---")
        st.subheader("🎯 题型筛选")
        selected_types = st.multiselect("只刷这些题型：", all_types, default=default_sel)
        if selected_types != default_sel:
            st.session_state.filters[st.session_state.active_bank] = selected_types
            st.session_state.progress[st.session_state.active_bank]["current_idx"] = 0
            st.session_state.q_start_time = None
            save_state()
            st.rerun()

        # 随机抽取 100 题
        st.markdown("---")
        if st.button("🔀 随机抽取 100 题（基于当前筛选）", use_container_width=True):
            # 构建可抽样列表
            filtered = [q for q in curr_q_list if q['type'] in selected_types]
            if not filtered:
                st.warning("当前筛选下没有题目，无法抽题。")
            else:
                sample_n = min(100, len(filtered))
                sampled = random.sample(filtered, sample_n)
                # 新建临时题库名
                tmp_name = f"{st.session_state.active_bank}_随机{sample_n}"
                # 拷贝并重置 progress
                st.session_state.banks[tmp_name] = [{**q, "user_answer": None} for q in sampled]
                st.session_state.progress[tmp_name] = {"history": {}, "wrong": [], "current_idx": 0, "times": {}}
                st.session_state.filters[tmp_name] = list({q['type'] for q in sampled})
                st.session_state.active_bank = tmp_name
                # 启动计时
                st.session_state.overall_start_time = time.time()
                st.session_state.q_start_time = None
                save_state()
                st.success(f"已创建题库：{tmp_name}，共 {sample_n} 题，已开始练习。")
                st.rerun()

    else:
        st.info("暂无题库，先导入一个 Excel。")

    # 错题区：导出、清空、存为新题库
    if st.session_state.active_bank:
        prog = st.session_state.progress.get(st.session_state.active_bank, {})
        wrong_cnt = len(prog.get('wrong', []))
        if wrong_cnt > 0:
            st.divider()
            st.subheader(f"📥 错题 ({wrong_cnt})")
            c1, c2 = st.columns(2)
            # 导出（导出格式可再次导入）
            def export_wrong_xlsx_bytes(wrong_list):
                rows = []
                for w in wrong_list:
                    rows.append({
                        "题目类型": w.get("type", ""),
                        "题目内容": w.get("raw_content", ""),
                        "正确答案": w.get("answer", ""),
                        "你的误选": w.get("user_answer", "")
                    })
                df = pd.DataFrame(rows)
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False)
                return out.getvalue()

            xls_bytes = export_wrong_xlsx_bytes(prog.get("wrong", []))
            c1.download_button("导出错题", xls_bytes, f"{st.session_state.active_bank}_错题.xlsx", use_container_width=True)

            with c2.expander("管理"):
                if st.button("清空错题", use_container_width=True):
                    prog["wrong"] = []
                    save_state()
                    st.success("已清空错题。")
                    st.rerun()
                if st.button("💾 将错题存为新题库", use_container_width=True):
                    new_name = f"{st.session_state.active_bank}_错题本"
                    if new_name in st.session_state.banks:
                        new_name += f"_{int(time.time())}"
                    new_qs = []
                    for wq in prog.get("wrong", []):
                        nq = wq.copy()
                        nq["user_answer"] = None
                        new_qs.append(nq)
                    st.session_state.banks[new_name] = new_qs
                    st.session_state.progress[new_name] = {"history": {}, "wrong": [], "current_idx": 0, "times": {}}
                    st.session_state.filters[new_name] = list({q['type'] for q in new_qs})
                    st.session_state.active_bank = new_name
                    save_state()
                    st.success(f"已创建并切换到题库：{new_name}")
                    st.rerun()

    st.divider()
    # 导入区（调用缓存解析）
    with st.expander("➕ 导入题库 (Excel)", expanded=(not bank_names)):
        uploaded = st.file_uploader("选择 Excel 文件 (.xlsx/.xls)", type=["xlsx", "xls"])
        name_input = st.text_input("题库命名（可选）")
        if uploaded and st.button("导入", type="primary", use_container_width=True):
            file_bytes = uploaded.getvalue()
            try:
                with st.spinner("解析 Excel，可能需要几秒..."):
                    qs = parse_excel_bytes(file_bytes)
            except Exception as e:
                st.error(f"导入失败：{e}")
            else:
                final_name = name_input.strip() if name_input.strip() else uploaded.name.split(".")[0]
                if final_name in st.session_state.banks:
                    final_name += f"_{int(time.time())}"
                st.session_state.banks[final_name] = qs
                # 初始化 progress：加 times 字段存每题时长
                st.session_state.progress[final_name] = {"history": {}, "wrong": [], "current_idx": 0, "times": {}}
                st.session_state.filters[final_name] = list({q['type'] for q in qs})
                st.session_state.active_bank = final_name
                st.session_state.overall_start_time = None
                st.session_state.q_start_time = None
                save_state()
                st.success(f"已导入题库：{final_name} （共 {len(qs)} 题）")
                st.rerun()

    # 删除库
    if st.session_state.active_bank:
        st.divider()
        with st.expander("⚠️ 删除当前题库"):
            if st.button("确认删除当前题库", use_container_width=True):
                name_del = st.session_state.active_bank
                del st.session_state.banks[name_del]
                del st.session_state.progress[name_del]
                del st.session_state.filters[name_del]
                st.session_state.active_bank = list(st.session_state.banks.keys())[0] if st.session_state.banks else None
                save_state()
                st.success("已删除题库。")
                st.rerun()

# --- 主界面：展示 / 答题区 ---
if not st.session_state.active_bank:
    st.markdown("<div style='text-align:center; padding:80px 0;'><h1>👋 欢迎使用 ZenMode</h1><p class='small-meta'>请在左侧侧边栏导入或选择题库</p></div>", unsafe_allow_html=True)
else:
    bk = st.session_state.active_bank
    full_qs = st.session_state.banks.get(bk, [])
    active_filters = st.session_state.filters.get(bk, list({q['type'] for q in full_qs}))
    qs = [q for q in full_qs if q['type'] in active_filters]

    pg = st.session_state.progress.setdefault(bk, {"history": {}, "wrong": [], "current_idx": 0, "times": {}})
    idx = pg.get("current_idx", 0)

    # 安全修正 idx 越界
    if idx > max(0, len(qs)):
        idx = len(qs)
        pg["current_idx"] = idx

    total_q = len(qs)
    done_q = min(idx + 1, total_q)
    wrong_q = len(pg.get("wrong", []))

    # HUD（显示 elapsed overall 和本题用时 if available）
    overall_elapsed = 0
    if st.session_state.overall_start_time:
        overall_elapsed = int(time.time() - st.session_state.overall_start_time)
    last_q_time = None
    if pg.get("times"):
        last_q_time = pg["times"].get(str(max(0, idx-1)), None)

    st.markdown(f"""
    <div class="hud-container">
        <div>
            <div class="hud-item">题库: <span class="hud-value">{bk}</span></div>
            <div class="small-meta">筛选：{', '.join(active_filters)}</div>
        </div>
        <div style="text-align:right;">
            <div class="hud-item">进度 <span class="hud-value hud-accent">{done_q}</span>/<span class="small-meta">{total_q}</span></div>
            <div class="hud-item">错题 <span class="hud-value hud-warn">{wrong_q}</span></div>
            <div class="small-meta">已用时: {overall_elapsed}s {('· 上题: ' + str(int(last_q_time)) + 's') if last_q_time else ''}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if total_q == 0:
        st.warning("当前筛选下没有题目。请在侧边栏调整题型筛选或导入题库。")
    elif idx >= total_q:
        st.markdown(f"<div style='text-align:center; padding:30px; background:#071223; border-radius:12px;'><h2>🎉 本题库已完成</h2><p class='small-meta'>共 {total_q} 题，错题 {wrong_q} 道</p></div>", unsafe_allow_html=True)
        if st.button("🔁 再刷一次", use_container_width=True, type="primary"):
            pg["current_idx"] = 0
            pg["history"] = {}
            pg["times"] = {}
            st.session_state.overall_start_time = time.time()
            st.session_state.q_start_time = None
            save_state()
            st.rerun()
    else:
        q = qs[idx]

        # 显示题目
        st.markdown(f"""
        <div class="zen-card">
            <span class="tag">{q['type']}</span>
            <div class="question-text">{q['content']}</div>
        </div>
        """, unsafe_allow_html=True)

        # 在题目首次渲染时启动计时
        if st.session_state.q_start_time is None:
            # 如果 overall_start_time 未设置，意味着新队列开始
            if st.session_state.overall_start_time is None:
                st.session_state.overall_start_time = time.time()
            st.session_state.q_start_time = time.time()

        user_choice = None
        saved = pg["history"].get(idx)

        # 渲染不同题型输入
        if q["code"] == "AO":
            sel_idx = 0 if saved == "A" else (1 if saved == "B" else None)
            val = st.radio("判断:", ["A", "B"], index=sel_idx, format_func=lambda x: "✅ 正确" if x=='A' else "❌ 错误", horizontal=True, key=f"{bk}_{idx}")
            user_choice = val
        elif q["code"] == "BO":
            if q.get("options"):
                keys = list(q["options"].keys())
                disp = [f"{k}. {v}" for k,v in q["options"].items()]
                sel_idx = keys.index(saved) if saved in keys else None
                val = st.radio("选择:", disp, index=sel_idx if sel_idx is not None else 0, key=f"{bk}_{idx}")
                user_choice = val.split(".")[0] if val else None
            else:
                user_choice = st.text_input("答案：", value=saved or "", key=f"txt_{bk}_{idx}").strip().upper()
        elif q["code"] == "CO":
            st.write("多项选择：")
            if q.get("options"):
                sel_list = []
                for k,v in q["options"].items():
                    checked = (k in saved) if saved else False
                    if st.checkbox(f"{k}. {v}", value=checked, key=f"{bk}_{idx}_{k}"):
                        sel_list.append(k)
                user_choice = "".join(sorted(sel_list)) if sel_list else ""
            else:
                user_choice = st.text_input("答案：", value=saved or "", key=f"txt_{bk}_{idx}").strip().upper()

        # 反馈占位
        feedback = st.empty()
        st.write("")
        c1, c2, c3 = st.columns([1,2,1])

        if c1.button("⬅ 上一题", disabled=(idx==0), use_container_width=True):
            pg["current_idx"] = max(0, idx-1)
            st.session_state.q_start_time = None
            save_state()
            st.rerun()

        if c2.button("提交 (Submit)", type="primary", use_container_width=True):
            if user_choice is None or (isinstance(user_choice, str) and user_choice.strip()==""):
                st.warning("请先作答")
            else:
                # 记录答案与用时
                pg["history"][idx] = user_choice
                now = time.time()
                q_elapsed = int(now - (st.session_state.q_start_time or now))
                # 存到 times 字典
                pg_times = pg.get("times", {})
                pg_times[str(idx)] = q_elapsed
                pg["times"] = pg_times

                ans = q.get("answer", "")
                if q["code"] == "AO":
                    if ans == "对": ans = "A"
                    if ans == "错": ans = "B"

                is_correct = (user_choice == ans)

                if is_correct:
                    feedback.markdown(f"""<div class="feedback-box feedback-success">✅ 回答正确！ 本题耗时：{q_elapsed}s</div>""", unsafe_allow_html=True)
                else:
                    feedback.markdown(f"""<div class="feedback-box feedback-error">❌ 回答错误。正确答案：<strong>{q.get('answer','')}</strong> · 本题耗时：{q_elapsed}s</div>""", unsafe_allow_html=True)
                    # 错题去重后入库
                    if not any(w.get("raw_content") == q.get("raw_content") for w in pg.get("wrong", [])):
                        # 把 user_answer 保存到错题记录
                        q_copy = q.copy()
                        q_copy["user_answer"] = user_choice
                        pg.setdefault("wrong", []).append(q_copy)

                # 自动保存并下一题（等待短暂时间让用户看结果）
                save_state()
                # 重置单题计时，下次渲染会重新设置
                st.session_state.q_start_time = None
                # 稍作停顿后前进
                time.sleep(0.9 if is_correct else 1.5)
                pg["current_idx"] = idx + 1
                save_state()
                st.rerun()

        if c3.button("跳过 ➡", use_container_width=True):
            pg["current_idx"] = idx + 1
            st.session_state.q_start_time = None
            save_state()
            st.rerun()