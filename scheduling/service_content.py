"""Patient information and validation, independent of diagnosis and ORM.

Guides explain questions to discuss at a visit; only a published clinic
presentation declares that a service is offered. No price is inferred.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class ServiceGuide:
    key: str
    title: str
    question: str
    summary: str
    discussion: tuple[str, ...]
    preparation: str
    boundary: str


GUIDES = (
    ServiceGuide('CHECKUP', '口腔检查与初诊', '想检查一下，或不知道该选哪项？',
        '先把困扰说清楚，了解牙齿、牙龈和口腔的情况，再与医师讨论下一步。',
        ('说明不适、既往就诊情况和本次最关心的问题。', '由医师检查口腔，解释发现和是否需要进一步检查。',
         '讨论可选方案、费用组成和后续安排。'),
        '准备既往相关检查、正在使用的药物及过敏信息；担心疼痛或紧张也可以提前告诉医师。',
        '初诊评估与后续治疗是不同的就诊环节，是否需要治疗由面诊决定。'),
    ServiceGuide('PREVENTION', '洁牙与牙龈护理', '想洁牙，或刷牙时容易出血？',
        '了解口腔清洁与牙龈状况，讨论适合自己的清洁护理和后续复查。',
        ('说明出血、不适与日常清洁情况。', '讨论是否适合本次洁牙或需要进一步牙周评估。',
         '了解护理方式、费用包含范围和复查安排。'),
        '带上相关就诊记录，向医师说明用药和过敏情况。',
        '洁牙与牙周治疗的范围、次数和费用可能不同；预约前请核对本店服务说明。'),
    ServiceGuide('RESTORATION', '牙痛与牙体修复', '牙疼、牙齿缺损，或补过的牙又不舒服？',
        '先评估问题，再讨论保留牙齿、修复缺损或转诊等可选路径。',
        ('说明疼痛位置、出现时间和已有治疗。', '由医师判断是否需要进一步检查。',
         '讨论方案、可能的多次就诊安排及各阶段费用。'),
        '整理症状出现的时间及既往相关检查、治疗记录。',
        '网页无法判断你需要补牙、根管治疗还是其他处理；请由医师面诊评估。'),
    ServiceGuide('CHILDREN', '儿童口腔就诊', '想带孩子检查牙齿？',
        '先了解孩子的口腔情况、配合需求和家长关心的问题，再讨论合适安排。',
        ('说明孩子的年龄、既往就诊经历及本次需求。', '了解本店接诊年龄和陪同要求。',
         '与医师讨论检查发现、护理建议和后续安排。'),
        '预约前向门店确认接诊年龄及监护人陪同、身份核验要求。',
        '本网站当前使用本人账号办理预约；儿童代办需由前台核验，不能用家长账号替孩子直接成约。'),
    ServiceGuide('ORTHODONTICS', '牙齿排列与正畸咨询', '想了解牙齿排列、咬合或矫正选择？',
        '以咨询评估为起点，了解可能的方案、时间投入及费用构成。',
        ('说明最希望改善的地方及既往治疗。', '讨论是否需要进一步检查与专科评估。',
         '了解治疗周期、复诊安排、费用和维护要求。'),
        '准备既往影像或相关治疗记录，以及希望与医师讨论的问题。',
        '咨询预约不代表已确定矫正方案，也不承诺治疗时长或效果。'),
    ServiceGuide('REPLACEMENT', '缺牙修复咨询', '缺牙后想了解有哪些修复方式？',
        '先评估口腔条件，与医师讨论可选修复方式和分阶段安排。',
        ('说明缺牙情况、既往修复经历与使用需求。', '讨论进一步检查及可选方案。',
         '了解各方案的维护要求、就诊次数和费用组成。'),
        '如有相关检查或修复记录，可带来供医师参考。',
        '咨询不等于已适合种植或其他修复方式，具体方案须经过面诊评估。'),
    ServiceGuide('FOLLOWUP', '复诊与治疗后复查', '已有治疗安排，需要按计划回来看看？',
        '衔接已有治疗计划，向原接诊团队说明恢复情况和新出现的问题。',
        ('核对原就诊记录与医师交代的复诊目的。', '说明本次需要反馈的问题。',
         '确认是否继续原安排或需要调整。'),
        '准备原就诊编号、相关检查和原接诊医师的复诊要求。',
        '需要专门复诊项目时，请选择与原计划一致的门店和服务，或联系原店前台。'),
    ServiceGuide('IMAGING', '影像检查相关评估', '已有医师建议，需要了解检查安排？',
        '核对医师的检查建议与已有资料，再确认适用检查和门店安排。',
        ('说明原医师的检查建议及已有影像。', '核对检查适用性和具体项目。',
         '确认费用、检查结果取得方式和后续解读安排。'),
        '带上原检查建议与已有资料；特殊健康情况请在检查前告知接诊团队。',
        '预约评估不代表一定拍片；具体检查须由医师判断，网页不会自动开立检查。'),
)
CATEGORY_CHOICES = tuple((g.key, g.title) for g in GUIDES) + (('OTHER', '其他就诊服务'),)
GUIDE_BY_KEY = {g.key: g for g in GUIDES}
FEE_CHOICES = (('ASSESSED', '评估后确认费用'), ('FIXED', '本次服务固定费用'), ('FROM', '本次服务起价'))
CONTENT_LIMITS = {'title': 100, 'summary': 240, 'suitable_for': 1600, 'visit_content': 2400,
                  'limitations': 1600, 'preparation': 1600, 'fee_note': 1600}
CONTENT_LABELS = {'title': '服务名称', 'summary': '服务价值说明', 'suitable_for': '适合的需求',
    'visit_content': '本次包含内容', 'limitations': '服务边界', 'preparation': '到诊准备', 'fee_note': '费用包含范围',
    'category': '服务分类', 'fee_mode': '费用方式', 'fee_amount': '费用金额', 'is_published': '公开状态'}
SOURCES = (
    ('Dental check-ups · NHS', 'https://www.nhs.uk/live-well/healthy-teeth-and-gums/dental-check-ups/'),
    ('Your dental appointment · NHS', 'https://www.nhs.uk/nhs-services/dentists/what-happens-when-you-visit-the-dentist/'),
    ('Toothache · NHS', 'https://www.nhs.uk/symptoms/toothache/'),
)
URGENT_NOTICE = '口腔或颈部肿胀已影响呼吸、吞咽或说话时，请立即寻求急救，不要等待网上预约。'


def validate_presentation(values):
    """Return field errors. Incomplete drafts are allowed; public copies are not."""
    errors = {}
    published = values.get('is_published', False)
    if type(published) is not bool:
        errors['is_published'] = '请选择是否公开展示。'
    for key, limit in CONTENT_LIMITS.items():
        value = values.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            errors[key] = f'请填写不超过{limit}字的文字。'
        elif published and not value.strip():
            errors[key] = '公开展示前请补齐此项。'
    if not isinstance(values.get('category'), str) or values['category'] not in dict(CATEGORY_CHOICES):
        errors['category'] = '请选择有效服务分类。'
    mode, amount = values.get('fee_mode'), values.get('fee_amount')
    if not isinstance(mode, str) or mode not in dict(FEE_CHOICES):
        errors['fee_mode'] = '请选择费用说明方式。'
    elif mode == 'ASSESSED':
        if amount is not None:
            errors['fee_amount'] = '评估后确认费用时请留空金额，不能用零元代替未知费用。'
    else:
        try:
            if isinstance(amount, (float, bool)) or amount is None:
                raise ValueError
            amount = Decimal(amount)
            if not amount.is_finite() or amount < 0 or amount > Decimal('9999999999.99') or amount != amount.quantize(Decimal('.01')):
                raise ValueError
        except (ValueError, TypeError, InvalidOperation):
            errors['fee_amount'] = '请填写明确的非负金额，最多两位小数。'
    return errors


def fee_label(mode, amount):
    if mode == 'ASSESSED' or amount is None:
        return '评估后确认费用'
    return f'¥{amount:.2f}' + (' 起' if mode == 'FROM' else ' / 本次服务')


def positive_id(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 18:
        return None
    return int(value) if int(value) > 0 else None


def patient_request(value):
    if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ValueError('就诊需求请填写不超过500字的文字。')
    return value.strip()


def presentation_values(profile):
    return {key: getattr(profile, key) for key in
        (*CONTENT_LIMITS, 'category', 'fee_mode', 'fee_amount', 'is_published')}


def operational_blockers(*, clinic_active, department_active, service_active, has_dentists, policy_enabled):
    checks = ((clinic_active, '门店尚未启用'), (department_active, '科室尚未启用'),
        (service_active, '预约服务已停用'), (has_dentists, '尚无可接收此服务的在用医师'),
        (policy_enabled, '本店接诊资源配置尚未启用'))
    return tuple(message for valid, message in checks if valid is not True)


def publication_readiness(values, *, operational_issues=()):
    """Publication readiness, not clinical approval or a promise of free slots."""
    if values is None:
        errors = {'summary': '尚未建立患者服务说明。'}
    else:
        errors = validate_presentation(dict(values, is_published=True))
    blockers = tuple(CONTENT_LABELS[key] + '：' + message for key, message in errors.items()) + tuple(operational_issues)
    published = values is not None and values.get('is_published') is True
    ready = not blockers
    if published and ready:
        code, label = 'PUBLISHED', '已公开'
    elif published:
        code, label = 'HIDDEN', '已隐藏，需核对'
    elif values is None:
        code, label = 'MISSING', '待创建服务说明'
    elif not ready:
        code, label = 'INCOMPLETE', '待完善'
    else:
        code, label = 'DRAFT', '草稿待发布'
    return {'code': code, 'label': label, 'blockers': blockers, 'content_ready': not errors,
        'can_publish': ready, 'visible': published and ready,
        'self_booking': published and ready and values.get('category') != 'CHILDREN'}


def draft_from_guide(category):
    """Editable content only: never assigns a service, invents a fee or publishes."""
    guide = GUIDE_BY_KEY.get(category)
    if guide is None:
        return {}
    return {'category': guide.key, 'title': guide.title, 'summary': guide.summary,
        'suitable_for': guide.question, 'visit_content': '\n'.join(guide.discussion),
        'limitations': guide.boundary, 'preparation': guide.preparation,
        'fee_mode': 'ASSESSED', 'fee_amount': None,
        'fee_note': '具体项目与费用在到诊评估后确认；另行安排的检查、治疗和材料需单独核对。',
        'is_published': False}
