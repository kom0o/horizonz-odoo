{
    'name': 'Employee Loans',
    'version': '1.0',
    'category': 'Human Resources',
    'summary': 'Manage Employee Loans and Debts',
    'description': """
Employee Loans and Debts Management
===================================
This module allows you to manage employee loans and debts.
    """,
    'author': 'Antigravity',
    'depends': ['hr', 'account', 'hr_payroll_community'],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_payroll_data.xml',
        'views/hr_loan_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
