{
    'name': 'Employee Specifications',
    'version': '1.0',
    'summary': 'Manage Monthly Employee Specifications and Accruals',
    'description': 'Module for tracking and managing monthly employee specifications (Medical, Visa, Iqama, etc) with automatic Journal Entries.',
    'category': 'Human Resources',
    'author': 'AI Agent',
    'depends': ['hr', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_employee_specification_views.xml',
    ],
    'installable': True,
    'application': False,
}
