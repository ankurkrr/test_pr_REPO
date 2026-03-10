# test_performance.py

def build_html(users):

    html = "<ul>"

    for u in users:
        # inefficient string concatenation
        html = html + "<li>" + u + "</li>"

    html = html + "</ul>"

    return html