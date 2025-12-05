import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pyzotero import zotero
import arxiv
from collections import Counter

# --- 1. 获取环境变量 ---
Z_ID = os.environ.get("ZOTERO_USER_ID")
Z_KEY = os.environ.get("ZOTERO_API_KEY")
EMAIL_USER = os.environ.get("EMAIL_USER")     # 你的发件邮箱地址
EMAIL_PASS = os.environ.get("EMAIL_PASS")     # 你的邮箱应用密码
RECEIVER = os.environ.get("EMAIL_RECEIVER")   # 接收推送的邮箱

def get_zotero_tags():
    """连接Zotero并分析你最近收藏文献的高频标签"""
    print("正在读取 Zotero 库...")
    zot = zotero.Zotero(Z_ID, 'user', Z_KEY)
    
    # 获取最近添加的 50 篇条目
    items = zot.top(limit=50)
    
    tags = []
    # 也可以把条目标题里的词也加进去，这里仅演示使用 Tags
    for item in items:
        if 'tags' in item['data']:
            for t in item['data']['tags']:
                tag_clean = t['tag'].lower()
                tags.append(tag_clean)
    
    # 统计出现频率最高的 5 个标签
    # 如果你的库没有标签，这里可能会空，建议平时养成打标习惯
    # 或者你可以手动在代码里追加几个固定关键词，例如： tags.extend(['fpga', 'transformer'])
    common_tags = [tag for tag, count in Counter(tags).most_common(5)]
    print(f"提取到的兴趣标签: {common_tags}")
    return common_tags

def search_arxiv(keywords):
    """根据关键词搜索过去24小时的论文"""
    if not keywords:
        return []
    
    print(f"正在 arXiv 搜索关键词: {keywords} ...")
    
    # 构建查询语句: (abs:tag1 OR abs:tag2) AND cat:cs.*
    # 限制在计算机科学(cs)领域，减少同名单词的噪音
    query_part = " OR ".join([f'abs:"{k}"' for k in keywords])
    search_query = f"({query_part}) AND cat:cs.*"

    client = arxiv.Client()
    search = arxiv.Search(
        query = search_query,
        max_results = 50, # 先多抓一点，再按时间过滤
        sort_by = arxiv.SortCriterion.SubmittedDate
    )

    results = []
    # 定义“昨天”的时间范围 (UTC时间)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1.5) # 稍微放宽到36小时以防时区差异漏掉

    for r in client.results(search):
        if r.published > yesterday:
            paper_info = (
                f"Title: {r.title}\n"
                f"Authors: {', '.join([a.name for a in r.authors[:3]])}\n"
                f"Link: {r.entry_id}\n"
                f"Published: {r.published.strftime('%Y-%m-%d')}\n"
                f"Summary: {r.summary[:200].replace(chr(10), ' ')}...\n"
                f"{'-'*30}"
            )
            results.append(paper_info)
    
    return results

def send_email(papers):
    """发送邮件"""
    if not papers:
        print("今日无符合条件的更新。")
        return

    print(f"准备发送 {len(papers)} 篇论文推送...")
    content = f"检测到您的 Zotero 关注领域有 {len(papers)} 篇 arXiv 新更新：\n\n" + "\n\n".join(papers)
    
    msg = MIMEText(content, 'plain', 'utf-8')
    msg['Subject'] = f"Arxiv Daily Push - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = EMAIL_USER
    msg['To'] = RECEIVER

    try:
        # 这里使用 Gmail 的服务器，如果是 QQ 邮箱用 smtp.qq.com, 端口 465 (SSL)
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print("邮件发送成功！")
    except Exception as e:
        print(f"邮件发送失败: {e}")

if __name__ == "__main__":
    tags = get_zotero_tags()
    if tags:
        new_papers = search_arxiv(tags)
        send_email(new_papers)
    else:
        print("未在 Zotero 中提取到有效标签，请检查 Zotero 库或手动指定关键词。")
