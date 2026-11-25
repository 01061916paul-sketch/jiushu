#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify_stage1.py - tender-pipeline 第一階段列表快篩核心邏輯
依據 Paul（九澍有限公司）兩大標準、13大排除清單與 A/B/C 分類規範。
嚴格維護恆等式：A + B + C = Total，零幻覺、零絕對詞。
"""

import sys
import os
import argparse
import json

def parse_row(line):
    parts = line.strip().split('\t')
    if len(parts) < 8:
        while len(parts) < 8:
            parts.append('')
    idx, org, cno, name, method_code_or_name, budget, pub_date, end_date = parts[:8]
    url = parts[8].strip() if len(parts) > 8 else ''
    return {
        'idx': idx.strip(),
        'org': org.strip(),
        'cno': cno.strip(),
        'name': name.strip(),
        'method_raw': method_code_or_name.strip(),
        'budget': budget.strip(),
        'pub_date': pub_date.strip(),
        'end_date': end_date.strip(),
        'url': url
    }

def format_method(method_raw):
    if method_raw == '2':
        return '經公開評選之限制性招標'
    elif method_raw == '1':
        return '公開取得報價單或企劃書'
    elif method_raw in ['0', '公開招標']:
        return '公開招標（最低標）'
    return method_raw

def classify_tender(t):
    name = t['name']
    method_code = t['method_raw']
    method_name = format_method(method_code)
    t['method_display'] = method_name
    budget = t['budget']

    # 13. 單純價格戰
    if method_code in ['0', '公開招標'] or '最低標' in method_name:
        return 'C', '單純價格戰'

    # 1. 非勞務（工程／財物）
    if any(k in name for k in ['宣導品', '宣傳品', '推廣品', '紀念品', '禮品', '燈箱製作', '紅包袋印製', '畢業紀念冊印製', '公務車租賃', '公務車駕駛', '購置案', '傢俱、會議設備規劃與購置', '設備採購']):
        return 'C', '非勞務（工程／財物）'
    if '工程' in name and any(k in name for k in ['整修工程', '改善工程', '新建工程', '修繕工程', '補強工程', '水利工程', '防水工程', '地坪工程', '建造工程', '防溢加勁土堤']) and not any(k in name for k in ['委託技術服務', '技術服務', '設計監造', '規劃設計', '可行性評估', '先期規劃']):
        return 'C', '非勞務（工程／財物）'

    # 2. 教育類
    if any(k in name for k in ['校外教學', '戶外教學', '戶外教育', '畢業旅行', '教育旅行', '隔宿露營', '童軍', '幼兒園校外', '增能參訪', '教育參訪', '成長營', '校外參觀', '參訪研習', '教育觀摩', '教育推廣', '環境教育推廣', '衛教', '母語', '社區大學', '部落大學', '課後照顧', '技藝教育']):
        return 'C', '教育類'

    # 3. 職能識能課程類
    if any(k in name for k in ['職能', '識能', '課程', '培育訓練', '培訓計畫', '研習場地', '人才養成', '職業訓練', '公費醫師培育', '講習', '里鄰長訓練', '幹部訓練', '自辦訓練']):
        return 'C', '職能識能課程類'

    # 4. 培力類
    if '培力' in name:
        return 'C', '培力類'

    # 5. 法律類
    if any(k in name for k in ['法律諮詢', '行政訴訟', '法規科學', '法規資料', '量刑鑑定', '法庭錄音委外轉譯', '調解民執', '調解委員', '律師', '訴訟']):
        return 'C', '法律類'

    # 6. 產業輔導、青年創業育成與就業輔導類
    if any(k in name for k in ['產業輔導', '地方型SBIR', '工廠實質改善輔導', '減廢輔導', '空污輔導', '低碳轉型與人才培育', '青年創業', '青創', '創業育成', '創業競賽', '就業輔導', '適性就業', '職涯諮詢', '求職登記', '求職防騙', '現場徵才', '就業隱私', '青年職涯', '職涯發展中心', '職務再設計']):
        return 'C', '產業輔導、青年創業育成與就業輔導類'

    # 7. 考古類
    if '考古' in name:
        return 'C', '考古類'

    # 純前台服務／開口庶務人力外包類（效益不佳）
    if any(k in name for k in ['前台服務', '巡演前台', '開口人力', '票務前台', '觀眾引導', '座位擺設']):
        return 'C', '純前台服務／開口庶務人力外包類（效益不佳）'

    # 出版品設計印刷類（大型印刷廠設備優勢，無競爭優勢）
    if any(k in name for k in ['出版品設計印製', '專書印製', '畫冊印製', '期刊印刷', '專輯出版印製', '文宣設計印製']):
        return 'C', '出版品設計印刷類（大型印刷廠設備優勢，無競爭優勢）'

    # 高頻新聞輿情監測與每日剪報類（人力耗損大且非核心企劃）
    if any(k in name for k in ['新聞輿情', '輿情監測', '每日剪報', '輿情蒐報', '即時輿情']):
        return 'C', '高頻新聞輿情監測與每日剪報類（人力耗損大且非核心企劃）'

    # 9. 需技師簽證或專業證照
    if any(k in name for k in [
        '規劃設計監造', '設計監造', '設計及監造', '規劃設計及監造', '規劃、設計、監造', '規劃、設計諮詢審查及施工監造',
        '監造技術服務', '委託技術服務', '監造案', '專案管理含監造', '設計服務案', '技術服務勞務', '監造開口契約',
        '規劃設計暨監造', '監造服務', '規劃設計及因應計畫技術服務', '委託規劃設計技術服務', '委託設計監造',
        '設計監造技術服務', '委託設計服務', '委託監造', '委託規劃設計', '委託勘測設計及監造', '委託勘查、設計及監造',
        '工程委託規劃', '工程委託設計', '消防安全設備檢修', '消防設備定檢', '消防安全設備檢驗及簽證申報',
        '公安檢查及申報', '結構檢討', '建築執照委託技術服務', '出流管制', '水土保持計畫', '可行性評估', '先期技術服務'
    ]):
        return 'C', '需技師簽證或專業證照'

    # 8. 需專業人員：○○
    if any(k in name for k in ['地籍圖重測', '多維度圖資測製', '委外測量', '地形圖套疊', '圖解數化', '用地取得查估', '土地徵收及協議價購市價及地上物']):
        return 'C', '需專業人員：地政'
    if any(k in name for k in ['FATCA', 'CRS', '代收、代繳用戶費款', '會計製單', '就學貸款對保', '收退費管理系統']):
        return 'C', '需專業人員：財務'
    if any(k in name for k in [
        '家庭服務中心', '青少年福利服務', '日間照顧', '社區照顧', '發展遲緩兒童', '家庭暴力', '托育', '托嬰',
        '身心障礙', '老人保護', '家庭處遇', '性影像處理中心', '非家暴老人', '新住民家庭', '新住民社區',
        '兒少保護', '安置服務', '老人健康照顧', '綜合福利場館', '獨居老人', '通報轉介', '個案管理', '成年監護',
        '白絲帶服務', '失能身心障礙', '庇護處所', '中途之家', '婦女館', '兒童綜合服務'
    ]):
        return 'C', '需專業人員：社工'
    if any(k in name for k in [
        '醫療支援', '醫師醫療服務', '特約醫師', '特約醫護', '病理檢驗', '代檢', '子宮頸抹片', '救護車轉院',
        '呼吸器', 'X光機', '次世代定序', '尿液篩檢', '乳房X光', '器官移植', '藥品', '藥事', '醫療器材',
        '醫師人力', '處方藥', '疫苗', '狂犬病', '愛滋病', '梅毒', '救護案', '放射性', '血液篩檢', '中藥（材）異常物質檢驗',
        '癌症預防管理', '醫護人員臨場'
    ]):
        return 'C', '需專業人員：醫療'
    if any(k in name for k in [
        '環境事故預防應變', '飛灰處理', '廢棄物清除', '廢水調節池', '污泥', '土壤及地下水', '水污染源',
        '空氣品質', '空品測站', '排煙檢測', '環境檢驗', '垃圾轉運', '掩埋場', '焚化', '底渣', '噪音監測',
        '環境影響評估', '水質檢測', 'PFAS', '代操作', '污水處理', '水質淨化', '廢棄物委外清運', '廚餘清運',
        '毒性及關注化學物質', '飲用水管理', '營建工程污染管制', '環境監測'
    ]):
        return 'C', '需專業人員：環工'
    if any(k in name for k in [
        '氣象風險', '洪水與淹水預警', '水文、警報', '地滑區監測', '坡面整體監測', '土石流及大規模崩塌',
        '沿近海漁業', '漁船海上作業查緝', '直升機委任運補', '土砂', '防砂', '崩塌', '集水區', '水土保持', '海岸防護', '滯洪池'
    ]):
        return 'C', '需專業人員：氣象與水文水保'
    if any(k in name for k in ['地球物理監測', '地質調查', '探勘', '碳封存', '地熱發電', '公墓有主(無)墳起掘', '空墳清除']):
        return 'C', '需專業人員：地質與礦產'
    if any(k in name for k in ['樹木調查', '樹木風險評估', '校園樹木', '捕蜂', '校樹褐根病', '植栽養護', '景觀養護', '園藝維護', '綠美化', '道路除草', '道路植栽']):
        return 'C', '需專業人員：農業與林業'
    if any(k in name for k in ['保全駐衛', '保全勤務', '駐衛保全', '駐衛警', '保全收款', '電子保全', '系統保全', '防盜系統保全', '保全、防護', '保全服務', '門禁、監控及保全']):
        return 'C', '需專業人員：保全'
    if any(k in name for k in [
        '環境清潔', '清潔維護', '校園清潔', '清潔勞務', '公墓雜草清除', '除草', '水肥清運', '園區清潔',
        '側溝清淤', '大樓清潔', '海堤漂流物', '路容清理', '向海致敬-海岸清潔', '割草', '清洗維護', '寢具委外清洗',
        '洗滌', '消毒', '清潔工作', '清潔管理', '鼠害防治', '病媒及害蟲', '流動廁所', '廁所衛生用品', '吸菸區清潔',
        '大樓環境清潔', '行舍環境清潔', '清潔外包'
    ]):
        return 'C', '需專業人員：清潔環衛'
    if any(k in name for k in [
        '機電設備維護', '水電維修', '水電設施', '空調設備', '電梯維護', '電梯保養', '消防設備', '不斷電系統',
        '柴油發電機', '高低壓電氣', '避雷器', '變壓器', '吹灰器', '電路板檢修', '水門', '抽水機', '抽水站',
        '高架地板', '路燈', '冷氣機安裝', '空調機具', '水電保養', '測速照相設備維修', '電力設施備援', '電力系統檢測',
        '消防系統檢測', '緊急求救系統保養', '火化爐'
    ]):
        return 'C', '需專業人員：機電空調工程'
    if any(k in name for k in [
        '汽車維修', '車輛保養', '重型機具租賃', '卡車保修', '午餐運輸', '冷藏運輸', '貨品運輸', '學生交通車',
        '專車租賃', '大客車租用', '社區巴士', '新巴士', '計程車接送', '駕駛勞務委外', '船舶帶解纜', '牽引車',
        '公車', '捷運路網', '路線運輸服務', '午餐運送', '委託運送', '接駁車租賃', '挖土機配合施工'
    ]):
        return 'C', '需專業人員：運輸與車輛保修'
    if any(k in name for k in ['保險採購', '保險案', '任意險', '公共意外責任險', '責任保險', '意外傷害保險', '意外險', '產物保險', '福利壽險', '產物火災及公共意外保險']):
        return 'C', '需專業人員：保險經紀'
    if any(k in name for k in ['資通安全', '資安專業顧問', '資安維護', '滲透測試', '資訊安全管理與防禦']):
        return 'C', '需專業人員：資訊安全'
    if any(k in name for k in [
        '系統維運', '系統維護', '設備維護', '軟體維護', '網路維護', '機房維運', '機房維護', '伺服器維護',
        '圖資雲維護', '通訊監察', '資訊維護', '資通安全維運', '資訊設備維護', '網站維護精進', '資料庫系統維護',
        '電腦設備維護', '線上申辦及審查系統', '下水道營運管理系統', '公文電子交換系統', '硬體設備汰換',
        '電腦資訊系統軟硬體委外維護', '資訊主機管理維護', '電腦機房主機伺服器', '審議服務平台建置作業委託資訊服務',
        '議事及相關資訊業務系統維護', '光纖網路優化'
    ]):
        return 'C', '需專業人員：資訊系統維護'
    if any(k in name for k in [
        '委外抄表', '抄表工作', '公文傳遞', '公文交換', '資料登錄', '卷證掃描', '檔案掃描', '郵件分揀',
        '工友', '庶務性業務', '行政庶務', '行政助理', '替代人力', '勞務承攬月薪人員', '服務人力委外',
        '駐點人員委外服務', '文書及事務勞務承攬', '公文收發', '郵件收發', '廚房清潔事務', '檔案、庫房維護作業及事務性管理',
        '總收發文及文書處理', '庶務性工作委外', '各類庶務業務委外', '話務中心勞務委託營運', '研究助理、行政作業'
    ]):
        return 'C', '需專業人員：庶務人力派遣'
    if any(k in name for k in [
        '餐會外燴', '圍爐餐會', '年終餐會', '外燴餐會', '伙食人力委外', '餐食服務採購', '外燴',
        '旺年聯誼餐會', '年終忘年會', '忘年會', '餐會活動', '娘家宴', '除夕餐會', '炊事清潔'
    ]):
        return 'C', '需專業人員：餐飲服務'
    if any(k in name for k in [
        '參訪觀摩', '日本參訪', '出國考察', '日本考察', '實地考察與交流', '宿霧市地區文化觀光',
        '聯誼活動', '弦樂團校際音樂交流', '參訪活動', '觀摩活動', '國際交流活動', '文康活動', '觀摩參訪',
        '國外觀摩', '知性文化交流暨經建考察', '校外交流', '義勇人員聯誼活動'
    ]):
        return 'C', '需專業人員：旅行業資源'
    if any(k in name for k in [
        '系統開發', '代理式AI', 'AI輔助', '軟體開發', '平台建置', '育兒資源網建置', '網路爬蟲',
        'Health GO系統優化與維運APP', '疫情智慧化監測系統建置', '網站共用平台暨人事相關系統維運'
    ]):
        return 'C', '需專業人員：軟體技術開發'
    if any(k in name for k in ['電視託播', '廣播託播', '廣告電視託播', '電臺宣傳採購', '節目製播計畫']):
        return 'C', '需專業人員：媒體廣告託播'
    if any(k in name for k in ['游泳池', '救生員', '運動防護']):
        return 'C', '需專業人員：體育休閒'

    # -------------------------------------------------------------
    # B 類判斷（待確認案件）
    # -------------------------------------------------------------
    is_protected_A = any(k in name for k in ['營運管理', '活動辦理', '活動執行', '承辦', '委託辦理', '策展', '企劃', '整合行銷'])
    has_B_keyword = any(k in name for k in ['製作', '施作', '拍攝', '印刷', '編印', '設計製作', '展覽佈置', '宣傳手冊', '印製', '製播', '佈置', '影像案', '雙⽉刊編製'])

    if has_B_keyword and not is_protected_A:
        return 'B', '性質待確認'

    if '建築調查研究' in name or '修復與再利用' in name or '文化資產' in name:
        return 'B', '是否需專業人員待確認'

    # -------------------------------------------------------------
    # A 類判斷（高潛力推薦）
    # -------------------------------------------------------------
    has_A_core = any(k in name for k in [
        '企劃', '規劃', '策展', '顧問', '研究', '評估', '活動企劃', '活動', '典禮', '展覽', '展售',
        '博覽會', '音樂節', '營運管理', '行銷', '宣導', '形象整合', '藝文月刊', '節慶', '文宣',
        '燈會', '文化節', '藝術季', '城市行銷', '推廣整合', '先期規劃', '滿意度調查', '政策評估',
        '品牌營造', '展演活動', '宣誓就職', '藝術行動', '音樂會', '花海節', '表揚典禮', '智慧城市展'
    ])

    if has_A_core:
        b_val = 0
        try:
            b_val = int(budget.replace(',', '').strip())
        except:
            pass
        if b_val > 10000000:
            reason = '業務類型符合（企劃／規劃／策展／顧問／研究／活動企劃與執行）需先看實績與資格門檻'
        else:
            reason = '業務類型符合（企劃／規劃／策展／顧問／研究／活動企劃與執行）'
        return 'A', reason

    return 'B', '列表資訊不足待確認'

def run_classification(input_path, output_dir=None):
    if not os.path.exists(input_path):
        print(f"Error: input file {input_path} does not exist", file=sys.stderr)
        sys.exit(1)

    with open(input_path, 'r', encoding='utf-8') as f:
        lines = [line for line in f if line.strip()]

    # 若第一行為標題列，自動跳過
    if lines and (lines[0].startswith('項次\t') or lines[0].startswith('項次')):
        lines = lines[1:]

    tenders = [parse_row(l) for l in lines]
    
    A_list = []
    B_list = []
    C_list = []

    for t in tenders:
        cat, reason = classify_tender(t)
        t['category'] = cat
        t['reason'] = reason
        if cat == 'A':
            A_list.append(t)
        elif cat == 'B':
            B_list.append(t)
        else:
            C_list.append(t)

    total = len(tenders)
    nA, nB, nC = len(A_list), len(B_list), len(C_list)
    assert nA + nB + nC == total, f"Invariant violated: {nA} + {nB} + {nC} != {total}"

    summary = f"共 {total} 筆，A 高潛力 {nA} 筆、B 待確認 {nB} 筆、C 排除 {nC} 筆"
    print(summary)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        # Write A, B, C tsv
        with open(os.path.join(output_dir, 'A_items.tsv'), 'w', encoding='utf-8') as fa:
            for t in A_list:
                fa.write('\t'.join([t['idx'], t['org'], t['cno'], t['name'], t['method_display'], t['budget'], t['end_date'], t['reason'], t.get('url', '')]) + '\n')
        with open(os.path.join(output_dir, 'B_items.tsv'), 'w', encoding='utf-8') as fb:
            for t in B_list:
                fb.write('\t'.join([t['idx'], t['org'], t['cno'], t['name'], t['method_display'], t['budget'], t['end_date'], t['reason'], t.get('url', '')]) + '\n')
        with open(os.path.join(output_dir, 'C_items.tsv'), 'w', encoding='utf-8') as fc:
            for t in C_list:
                fc.write('\t'.join([t['idx'], t['org'], t['cno'], t['name'], t['method_display'], t['budget'], t['end_date'], t['reason'], t.get('url', '')]) + '\n')

    return summary, A_list, B_list, C_list

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Tender Pipeline Stage 1 Classifier")
    parser.add_argument("input_file", help="Path to input TSV file with today's tenders")
    parser.add_argument("--output_dir", "-o", help="Optional output directory to save A/B/C TSVs", default=None)
    args = parser.parse_args()

    run_classification(args.input_file, args.output_dir)
