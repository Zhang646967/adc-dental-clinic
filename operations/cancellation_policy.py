"""B1.1 business definitions, shared by reporting and improvement reviews."""
from datetime import date
from operations.policies import percent, summarize
from adc_core.rules import RuleError

BANDS = [('08_10', '08:00–10:00'), ('10_12', '10:00–12:00'),
         ('12_14', '12:00–14:00'), ('14_16', '14:00–16:00'),
         ('16_18', '16:00–18:00'), ('18_20', '18:00–20:00'), ('OTHER', '其他时段')]
WEEKDAYS = [(1, '星期一'), (2, '星期二'), (3, '星期三'), (4, '星期四'),
            (5, '星期五'), (6, '星期六'), (7, '星期日')]
REASONS = [('UNSUPPLIED', '未提供／待核实'), ('SCHEDULE', '患者行程变化'),
           ('CONTACT', '遗忘或联系问题'), ('COST', '费用顾虑'),
           ('CLINIC', '诊所／医师调整'), ('OTHER', '其他已核实原因')]
FOLLOW_STATES = [('OPEN', '待联系'), ('WAITING', '等待回复'),
                 ('REBOOKED', '已另约'), ('DECLINED', '患者暂不预约'), ('NO_ACTION', '无需再联系')]
PENDING_FOLLOW = ('OPEN', 'WAITING')
KINDS = [('CONTACT', '联系确认与到诊提示'), ('RESCHEDULE', '协助选择替代时间'),
         ('WAITLIST', '候补补位协调'), ('SCHEDULING', '出诊调整协调'), ('VERIFY', '核实缺失结果和原因')]
ACTION_STATES = [('OPEN', '待开始'), ('WORKING', '执行中'), ('READY', '待复核'),
                 ('CLOSED', '已复核'), ('CANCELLED', '已终止')]
ACTION_NAMES = [('CREATE', '建立改进措施'), ('START', '开始执行'), ('ASSIGN', '调整责任与期限'),
                ('SUBMIT', '提交执行结果'), ('RETURN', '退回继续办理'),
                ('REVIEW', '复核措施结果'), ('CANCEL', '终止措施')]
ASSESSMENTS = [('OBSERVED', '已核对变化，继续观察'), ('INSUFFICIENT', '样本或完整性不足'),
               ('NOT_COMPARABLE', '窗口或业务结构不可比')]
POLICY = 'ADC-CANCEL-1'

def band_for_hour(hour):
    return f'{hour//2*2:02}_{hour//2*2+2:02}' if 8 <= hour < 20 else 'OTHER'

def metric_dict(groups):
    m = summarize(groups)
    result = {k: getattr(m, k) for k in ('arrived', 'patient_cancel', 'clinic_cancel',
              'no_show', 'pending', 'denominator', 'cancel_rate', 'no_show_rate', 'completeness')}
    result['overall_denominator'] = m.denominator + m.clinic_cancel
    result['overall_rate'] = percent(m.patient_cancel + m.clinic_cancel, result['overall_denominator'])
    result['eligible'] = m.denominator >= 30 and m.completeness is not None and m.completeness >= 95
    result['sample_note'] = '可列调查优先项' if result['eligible'] else (
        '样本不足' if m.denominator < 30 else '先核实到期结果')
    return result

def serialize_metrics(data):
    return {k: str(v) if k.endswith(('_rate', 'completeness')) and v is not None else v
            for k, v in data.items()}

def valid_cell(weekday, band):
    if type(weekday) is not int or weekday not in range(1, 8) or band not in dict(BANDS):
        raise RuleError('请选择有效的星期和开始时段。')

def review_window(start, end, baseline_end):
    from operations.policies import period_bounds
    period_bounds(start, end)
    if start <= baseline_end:
        raise RuleError('复核窗口须位于原观察窗口之后，不能重叠。')
