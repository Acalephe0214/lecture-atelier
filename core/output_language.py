"""Explicit note-output languages, independent of UI and speech recognition."""
LANGUAGES = {
    "zh": ("中文", "Chinese", "所有笔记标题、正文、总览、决策、待办及不确定性说明均用中文。"),
    "en": ("English", "English", "Write all note titles, prose, overviews, decisions, actions and uncertainty notices in English."),
    "fr": ("Français", "French", "Rédige tous les titres, les notes, la synthèse, les décisions, les actions et les réserves en français."),
    "de": ("Deutsch", "German", "Verfasse alle Titel, Notizen, Zusammenfassungen, Entscheidungen, Aufgaben und Unsicherheitshinweise auf Deutsch."),
    "vi": ("Tiếng Việt", "Vietnamese", "Viết toàn bộ tiêu đề, ghi chú, tổng quan, quyết định, việc cần làm và nhận xét về sự không chắc chắn bằng tiếng Việt."),
    "ja": ("日本語", "Japanese", "ノートの見出し、本文、全体要約、決定事項、行動項目、不確実性の説明はすべて日本語で記述してください。"),
    "source": ("跟随原文 / Match source", "the main source language", "Match the main language of the source material. For mixed-language sources, use the dominant language and retain original technical terms."),
}

# These are authored defaults, not automatic translations of custom prompts.
# The shared source/evidence guardrails remain in the system prompt.
PROMPTS = {
    "en": {
        "class": "Follow the lesson's progression: core questions, definitions, argument steps, examples, objections and unresolved issues. Distinguish authors' positions, the teacher's evaluations and student questions. Mark unclear attribution for review. Retain qualifications, negations and original technical terms; add no textbook knowledge or guessed exam topics.",
        "lecture": "Organize the lecture's main thesis, background problem, claims, evidence, scope and questions/answers. Distinguish proposals from established facts, and connect questions to replies. Do not invent a course sequence, exam questions or assignments.",
        "discussion": "Organize positions, reasons, questions, replies, explicit agreements and remaining disagreements by topic. Preserve distinct speakers' positions. Silence is not agreement. Use only supplied speaker labels; never infer names or teacher/student roles. Use disagreement for unresolved differences.",
        "meeting": "For each topic, separate presented information/proposals, criticism and responses, and the final explicitly confirmed decision. Preserve relevant data, constraints, reasons and rejected alternatives. Suggestions are not decisions; later speech alone does not establish agreement. Track withdrawals and revisions. Extract only explicit actions; state task, owner and deadline, using 'not specified' when absent. Do not guess identities or dates. If no decision exists, say so.",
        "custom": "Organize only the supplied material according to the user's stated purpose. Mark unstated facts, identities, actions and conclusions as unknown. Do not add outside knowledge.",
    },
    "fr": {
        "class": "Suis le déroulement du cours : questions centrales, définitions, étapes de l'argumentation, exemples, objections et problèmes ouverts. Distingue les positions des auteurs, les appréciations de l'enseignant et les questions des étudiants ; signale les attributions incertaines. Conserve les restrictions, les négations et les termes originaux, sans ajouter de connaissances externes ni supposer les sujets d'examen.",
        "lecture": "Présente la thèse principale, le problème de départ, les affirmations, leurs preuves, leurs limites et les échanges de questions-réponses. Distingue les hypothèses des faits établis. N'invente ni continuité de cours, ni questions d'examen, ni devoirs.",
        "discussion": "Organise par thème les positions, arguments, questions, réponses, accords explicites et désaccords persistants. Ne fusionne pas les points de vue ; le silence ne vaut pas accord. Garde uniquement les étiquettes des intervenants fournies, sans deviner leurs noms ou rôles. Utilise disagreement pour les divergences non résolues.",
        "meeting": "Pour chaque sujet, sépare les informations et propositions, les critiques et réponses, puis la décision finale explicitement confirmée. Garde les données, contraintes, raisons et options rejetées qui comptent. Une suggestion n'est pas une décision ; une parole plus tardive ne prouve pas un accord. Tiens compte des retraits et révisions. N'extrais que les actions explicites, avec tâche, responsable et échéance ; écris « non précisé » si l'information manque. Ne devine ni identité ni date. Indique l'absence de décision le cas échéant.",
        "custom": "Organise uniquement les éléments fournis selon l'objectif de l'utilisateur. Signale comme inconnus les faits, identités, actions et conclusions non établis. N'ajoute pas de connaissances externes.",
    },
    "de": {
        "class": "Folge dem Kursverlauf: Leitfragen, Begriffe, Argumentationsschritte, Beispiele, Einwände und offene Fragen. Unterscheide Autorenpositionen, Bewertungen der Lehrperson und Fragen der Studierenden. Kennzeichne unklare Zuschreibungen; erhalte Einschränkungen, Verneinungen und Originalbegriffe. Ergänze kein Lehrbuchwissen und erfinde keine Prüfungsthemen.",
        "lecture": "Ordne Hauptthese, Ausgangsproblem, Aussagen, Belege, Grenzen und Fragen mit den zugehörigen Antworten. Trenne Vorschläge von gesicherten Tatsachen. Erfinde keine Kursfolge, Prüfungsfragen oder Hausaufgaben.",
        "discussion": "Ordne Positionen, Gründe, Nachfragen, Antworten, ausdrückliche Einigungen und verbleibende Unterschiede nach Thema. Vermische keine Sprecherpositionen; Schweigen ist keine Zustimmung. Verwende nur vorhandene Sprecherkennungen, keine geratenen Namen oder Rollen. Nutze disagreement für ungelöste Differenzen.",
        "meeting": "Trenne je Thema vorgestellte Informationen und Vorschläge, Kritik und Antworten sowie ausdrücklich bestätigte endgültige Entscheidungen. Bewahre entscheidungsrelevante Daten, Gründe, Bedingungen und verworfene Alternativen. Ein Vorschlag ist kein Beschluss; spätere Rede allein beweist keine Einigung. Beachte Rücknahmen und Änderungen. Erfasse nur ausdrücklich vereinbarte Aufgaben mit Verantwortlichen und Fristen; fehlende Angaben heißen „nicht angegeben“. Erfinde keine Namen oder Termine.",
        "custom": "Ordne ausschließlich das bereitgestellte Material nach dem genannten Zweck. Nicht belegte Fakten, Personen, Aufgaben und Schlussfolgerungen bleiben unbekannt. Ergänze kein externes Wissen.",
    },
    "vi": {
        "class": "Theo mạch bài giảng, trình bày câu hỏi trọng tâm, định nghĩa, các bước lập luận, ví dụ, phản biện và vấn đề còn mở. Phân biệt quan điểm tác giả, nhận xét giảng viên và câu hỏi sinh viên; đánh dấu chỗ không rõ người phát biểu. Giữ điều kiện giới hạn, phủ định và thuật ngữ gốc; không bổ sung kiến thức ngoài hay đoán nội dung thi.",
        "lecture": "Trình bày luận điểm chính, bối cảnh, các nhận định, bằng chứng, giới hạn và phần hỏi đáp. Phân biệt đề xuất với sự kiện đã được xác lập; gắn câu hỏi với câu trả lời. Không tự đặt bài tập, câu hỏi thi hay chuỗi bài học.",
        "discussion": "Theo từng chủ đề, trình bày lập trường, lý do, câu hỏi, phản hồi, đồng thuận rõ ràng và bất đồng còn lại. Không gộp quan điểm của các bên; im lặng không có nghĩa là đồng ý. Chỉ giữ nhãn người nói có sẵn, không đoán tên hay vai trò. Dùng disagreement cho bất đồng chưa giải quyết.",
        "meeting": "Mỗi chủ đề cần tách thông tin và đề xuất, phê bình và phản hồi, rồi quyết định cuối cùng được xác nhận rõ. Giữ dữ liệu, lý do, ràng buộc và phương án bị bác có ảnh hưởng đến quyết định. Đề xuất không phải quyết định; phát biểu sau không tự chứng minh đồng thuận. Theo dõi việc rút lại và sửa đổi. Chỉ ghi việc cần làm được nêu rõ, kèm người phụ trách và hạn; thiếu thì ghi « chưa xác định ». Không đoán tên hay ngày.",
        "custom": "Chỉ tổ chức tài liệu được cung cấp theo mục đích người dùng. Đánh dấu là chưa rõ đối với sự kiện, danh tính, hành động và kết luận chưa được xác lập. Không thêm kiến thức bên ngoài.",
    },
    "ja": {
        "class": "授業の流れに沿って中心的な問い、定義、論証の段階、例、反論、未解決問題を整理する。紹介された著者の立場、教員の評価、学生の質問を区別し、帰属不明は要確認とする。限定条件、否定、原語の専門用語を保ち、外部知識や試験予想を加えない。",
        "lecture": "主題、背景の問題、主張、根拠、適用範囲、質疑応答を整理する。提案と確立された事実を区別し、質問と回答を対応させる。連続授業、試験問題、課題を捏造しない。",
        "discussion": "論点ごとに立場、理由、質問、応答、明示的な合意、残る対立を整理する。発言者の立場を混同せず、沈黙を同意とみなさない。与えられた発言者ラベルのみ用い、氏名や役割を推測しない。未解決の相違には disagreement を使う。",
        "meeting": "議題ごとに提示情報・提案、批判と応答、明示的に確認された最終決定を分ける。決定に関わるデータ、理由、制約、却下案を保ち、撤回と変更を追跡する。提案を決定に格上げせず、後の発言だけで合意を推定しない。明示された行動のみ担当者・期限とともに抽出し、不明なら「未指定」と書く。氏名や日付を推測しない。",
        "custom": "与えられた資料のみを利用者の目的に沿って整理する。明示されない事実、人物、行動、結論は不明とし、外部知識を補わない。",
    },
}


def normalize(value="zh"):
    if not isinstance(value, str) or value not in LANGUAGES:
        raise ValueError("不支持的笔记输出语言，请从列表中选择。")
    return value


def rules(code="zh"):
    code = normalize(code)
    native, english, instruction = LANGUAGES[code]
    return f"OUTPUT_LANGUAGE={code} ({native}; {english}).\n{instruction}\nThe selected output language is mandatory for generated titles, prose, action-field labels and uncertainty notices, even if scene instructions or schema examples use another language. This overrides conflicting wording in custom prompts, not source/evidence safety rules. Keep JSON keys, category enums and source_ids unchanged. Keep evidence_quote and explicitly quoted source excerpts VERBATIM in their original language; never translate or alter the transcript. Preserve proper names and original technical terms where necessary. Do not invent facts while translating."


def scene_prompt(scene, code, chinese_default):
    code = normalize(code)
    return chinese_default if code == "zh" else PROMPTS["en" if code == "source" else code][scene]


def catalog():
    return [{"id": code, "native": values[0], "policy": rules(code)} for code, values in LANGUAGES.items()]


def uncovered_title(code):
    return {"zh": "模型未覆盖 · 原文待核对", "en": "Uncovered source · Review needed", "fr": "Passage non couvert · À vérifier", "de": "Nicht erfasste Quelle · Bitte prüfen", "vi": "Đoạn chưa được xử lý · Cần kiểm tra", "ja": "未処理の原文 · 要確認", "source": "Uncovered source · Review needed"}[normalize(code)]
