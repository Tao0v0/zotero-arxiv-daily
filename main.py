import os
import smtplib
import json
import time
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pyzotero import zotero
import arxiv
import google.generativeai as genai

# --- 1. 基础配置 ---
# 从 GitHub Secrets 读取配置
Z_ID = os.environ.get("ZOTERO_USER_ID")
Z_KEY = os.environ.get("ZOTERO_API_KEY")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
RECEIVER = os.environ.get("EMAIL_RECEIVER")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# --- 2. 你的科研兴趣画像 (已为你定制) ---
def get_research_profile():
    """
    这里定义了 AI 评分的标准。
    基于你的背景，我已经把 FPGA、INT8、ViT 等关键词预埋进去了。
    """
    return """
    I am a researcher focusing on Hardware-Aware AI and Model Deployment.
    
    My core research interests are:
    1. **FPGA Acceleration**: Deploying deep learning models on FPGAs (Xilinx/AMD), focusing on accelerator design.
    2. **Model Compression**: Specifically **INT8 quantization**, mixed-precision training, and model pruning.
    3. **Vision Transformers (ViT)**: Hardware optimization for ViTs, position embeddings, and efficient attention mechanisms.
    4. **Efficient Attention**: Hardware-friendly implementations of attention (e.g., FlashAttention).
    5. **Embedded Systems**: Zynq/PYNQ platforms and edge computing.

    Please evaluate the paper based on how closely it relates to these hardware/efficiency topics.
    """

def get_keywords_from_zotero():
    """从 Zotero 提取标签，并补充核心关键词"""
    keywords = set()
    
    # 1. 尝试从 Zotero 读取 (如果失败则跳过)
    try:
        if Z_ID and Z_KEY:
            zot = zotero.Zotero(Z_ID, 'user', Z_KEY)
            items = zot.top(limit=20)
            for item in items:
                if 'tags' in item['data']:
                    for t in item['data']['tags']:
                        # 只要英文标签，避免搜索报错
                        if t['tag'].isascii():
                            keywords.add(t['tag'])
    except Exception as e:
        print(f"Zotero 读取跳过: {e}")

    # 2. 强制补充你的核心领域词 (保证即使 Zotero 没标签也能搜到)
    # 这里的词用于去 Arxiv 广撒网
    core_keywords = ["FPGA", "Quantization", "Vision Transformer", "Hardware Accelerator"]
    final_keywords = list(keywords) + core_keywords
    
    # 限制关键词数量，防止 URL 太长报错
    return final_keywords[:6]

def search_arxiv(keywords):
    """在 arXiv 搜索过去 24 小时的论文"""
    print(f"搜索关键词: {keywords}")
    
    # 构建查询语句: (abs:"FPGA" OR abs:"ViT" ...) AND cat:cs.*
    query_part = " OR ".join([f'abs:"{k}"' for k in keywords])
    search_query = f"({query_part}) AND cat:cs.*"
    
    client = arxiv.Client()
    search = arxiv.Search(
        query = search_query,
        max_results = 40, # 抓取前 40 篇给 AI 挑
        sort_by = arxiv.SortCriterion.SubmittedDate
    )
    
    candidates = []
    # 设定时间范围：过去 36 小时 (涵盖时区差)
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

def ai_review_paper(paper, interest_profile):
    """调用 Gemini 给论文打分"""
    # 配置 Gemini
    genai.configure(api_key=GEMINI_KEY)
    
    # 使用 Gemini 3 (速度快、免费额度高)
    model = genai.GenerativeModel(
        'gemini-3',
        generation_config={"response_mime_type": "application/json"}
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
    
    Output strictly in JSON format:
    {{
        "score": 8,
        "reason": "This paper proposes a new INT8 quantization method specifically for ViTs on FPGA."
    }}
    """

    try:
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini 分析出错: {e}")
        time.sleep(1) # 避让
        return {"score": 0, "reason": "Error"}

def main():
    # 检查 Key 是否存在
    if not GEMINI_KEY:
        print("错误：GitHub Secrets 中未找到 GEMINI_API_KEY，无法运行 AI 评分。")
        return

    # 1. 获取数据
    profile = get_research_profile()
    keywords = get_keywords_from_zotero()
    candidates = search_arxiv(keywords)
    
    if not candidates:
        print("今日无符合关键词的新论文。")
        return

    # 2. AI 评分
    print(f"开始 AI 智能评审 (共 {len(candidates)} 篇)...")
    high_quality_papers = []
    
    for paper in candidates:
        # 调用 Gemini
        review = ai_review_paper(paper, profile)
        score = review.get('score', 0)
        
        print(f"[{score}分] {paper['title'][:40]}...")
        
        # 筛选阈值：7分以上才推送
        if score >= 7:
            paper['score'] = score
            paper['reason'] = review.get('reason', 'N/A')
            high_quality_papers.append(paper)
        
        # 稍微延时，防止触发 API 速率限制
        time.sleep(2)

    # 3. 发送邮件
    high_quality_papers.sort(key=lambda x: x['score'], reverse=True)
    
    if high_quality_papers:
        count = len(high_quality_papers)
        print(f"最终筛选出 {count} 篇高分论文，正在发送...")
        
        # 构建邮件正文
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
            # 兼容 Gmail 和大部分邮箱的 SSL 端口
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
