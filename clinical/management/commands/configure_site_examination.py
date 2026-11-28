from clinical.examination_setup import ProjectCommand


class Command(ProjectCommand):
    help = '开通、暂停本机构的检查项目，维护执行和独立审核职责。'
    site = True
