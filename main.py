import os
import smtplib
import json
import time
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pyzotero import zotero
import arxiv
from openai import OpenAI  # <--- 改用 OpenAI 库

# --- 1. 基础配置 ---
Z_ID = os.environ.get("ZOTERO_USER_ID")
Z_KEY = os.environ.get("ZOTERO_API_KEY")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
RECEIVER = os.environ.get("EMAIL_RECEIVER")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BASE_URL = os.environ.get("GEMINI_BASE_URL")

# --- 2. 你的科研兴趣画像 ---
def get_research_profile():
    return """
    I am a researcher focusing on Hardware-Aware AI and Model Deployment.
    
    My core research interests are:
    1. **FPGA Acceleration**: Deploying deep learning models on FPGAs (Xilinx/AMD).
    2. **Model Compression**: Specifically **INT8 quantization**, mixed-precision, and pruning.
    3. **Vision Transformers (ViT)**: Hardware optimization for ViTs.
    4. **Efficient Attention**: Hardware-friendly attention (e.g., FlashAttention).
    5. **Embedded Systems**: Zynq/PYNQ platforms.

    Please evaluate the paper based on these topics.
    """

def get_keywords_from_zotero():
    """同原代码，省略重复部分，保持不变"""
    keywords = set()
    try:
        if Z_ID and Z_KEY:
            zot = zotero.Zotero(Z_ID, 'user', Z_KEY)
            items = zot.top(limit=20)
            for item in items:
                if 'tags' in item['data']:
                    for t in item['data']['tags']:
                        if t['tag'].isascii():
                            keywords.add(t['tag'])
    except Exception as e:
        print(f"Zotero 读取跳过: {e}")

    core_keywords = ["FPGA", "Quantization", "Vision Transformer", "Hardware Accelerator"]
    final_keywords = list(keywords) + core_keywords
    return final_keywords[:6]

def search_arxiv(keywords):
    """同原代码，保持不变"""
    # ... (保持你原来 search_arxiv 的代码完全不变) ...
    # 为节省篇幅这里不重复写，请保留你原来的 search_arxiv 函数
    print(f"搜索关键词: {keywords}")
    query_part = " OR ".join([f'abs:"{k}"' for k in keywords])
    search_query = f"({query_part}) AND cat:cs.*"
    
    client = arxiv.Client()
    search = arxiv.Search(
        query = search_query,
        max_results = 40,
        sort_by = arxiv.SortCriterion.SubmittedDate
    )
    
    candidates = []
    yesterday = datetime.now(timezone.utc) - timedelta(hours=36)
    
    for r in client.results(search):
        if r.published > yesterday:
            candidates.append({
                "title": r.title,
                "abstract": r.summary.replace("\n", " "),
                "url": r.entry_id,
                "authors": ", ".join([a.name for a in r.authors[:3]])
            })
            
    print(f"arXiv 初筛找到 {len(candidates)} 篇近期论文...")
    return candidates

# --- 3. 核心修改：AI 评分函数 ---
def ai_review_paper(paper, interest_profile):
    """使用 OpenAI 兼容协议调用中转站的 Gemini"""
    
    # 修正 Base URL 格式：通常中转站需要在末尾加 /v1
    # 如果你的 Secrets 里已经是 https://api.chataiapi.com/v1 则不需要拼接
    api_base = BASE_URL
    if api_base and not api_base.endswith('/v1'):
        api_base = f"{api_base}/v1"

    client = OpenAI(
        api_key=GEMINI_KEY,
        base_url=api_base
    )

    prompt = f"""
    You are a research assistant.
    User Profile:
    {interest_profile}

    Paper to evaluate:
    Title: {paper['title']}
    Abstract: {paper['abstract']}

    Task:
    1. Score relevance from 0 to 10 (10 = Must read for my hardware/FPGA research).
    2. Provide a brief reason (1 sentence).
    
    Output strictly in JSON format like: {{"score": 8, "reason": "..."}}
    """

    try:
        # 中转站通常把 gemini 映射为 gemini-pro 或 gemini-1.5-flash
        # 注意：这里不能用 gemini-3，大部分中转站不支持瞎写的名字
        response = client.chat.completions.create(
            model="gemini-1.5-flash", 
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"} # 强制 JSON 模式，防止格式错误
        )
        
        content = response.choices[0].message.content
        return json.loads(content)
        
    except Exception as e:
        print(f"AI 分析出错: {e}")
        time.sleep(1)
        return {"score": 0, "reason": "Error"}

def main():
    # ... (保持你原来 main 的代码完全不变) ...
    # 只需要保留原来的 main 函数即可
    if not GEMINI_KEY:
        print("错误：GitHub Secrets 中未找到 GEMINI_API_KEY")
        return

    profile = get_research_profile()
    keywords = get_keywords_from_zotero()
    candidates = search_arxiv(keywords)
    
    if not candidates:
        print("今日无符合关键词的新论文。")
        return

    print(f"开始 AI 智能评审 (共 {len(candidates)} 篇)...")
    high_quality_papers = []
    
    for paper in candidates:
        review = ai_review_paper(paper, profile)
        score = review.get('score', 0)
        
        print(f"[{score}分] {paper['title'][:40]}...")
        
        if score >= 7:
            paper['score'] = score
            paper['reason'] = review.get('reason', 'N/A')
            high_quality_papers.append(paper)
        
        time.sleep(2)

    high_quality_papers.sort(key=lambda x: x['score'], reverse=True)
    
    if high_quality_papers:
        count = len(high_quality_papers)
        print(f"最终筛选出 {count} 篇高分论文，正在发送...")
        
        content = f"Gemini 为您精选了 {count} 篇 FPGA/AI 硬件相关论文 ({datetime.now().strftime('%Y-%m-%d')})：\n\n"
        for p in high_quality_papers:
            content += f"【{p['score']}分】 {p['title']}\n"
            content += f"推荐理由: {p['reason']}\n"
            content += f"链接: {p['url']}\n"
            content += "-" * 40 + "\n"
            
        msg = MIMEText(content, 'plain', 'utf-8')
        msg['Subject'] = f"🔥 Arxiv日报: {count} 篇精选 (FPGA/ViT/Quant)"
        msg['From'] = EMAIL_USER
        msg['To'] = RECEIVER

        try:
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465) 
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
            server.quit()
            print("✅ 邮件发送成功！")
        except Exception as e:
            print(f"❌ 邮件发送失败: {e}")
    else:
        print("今日虽然有新论文，但 AI 认为相关度均未达到 7 分，不打扰您。")

if __name__ == "__main__":
    main()
