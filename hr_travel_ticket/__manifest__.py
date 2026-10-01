{
    'name': 'Employee Travel Tickets',
    'version': '1.0',
    'summary': 'Manage Employee Travel Tickets',
    'description': 'Module for tracking and managing employee travel ticket requests.',
    'category': 'Human Resources',
    'author': 'AI Agent',
    'depends': ['hr'],
    'data': [
        'security/ir.model.access.csv',
        'views/travel_ticket_views.xml',
    ],
    'installable': True,
    'application': False,
}
