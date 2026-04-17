def migrate(cr, version):
    """Archive the default medical locations created in earlier versions.
    We archive instead of delete because stock moves may reference them."""
    default_location_names = [
        'Medical Center',
        'Main Medical Store',
        'Clinic 1',
        'Clinic 2',
        'Clinic 3',
        'Emergency Department',
        'Pharmacy',
    ]
    placeholders = ','.join(['%s'] * len(default_location_names))

    # Archive the locations so they disappear from all dropdowns
    cr.execute(f"""
        UPDATE stock_location
        SET active = false
        WHERE name IN ({placeholders})
        AND usage IN ('internal', 'view')
    """, default_location_names)
