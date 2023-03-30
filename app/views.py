from flask import Flask, render_template, request, make_response, jsonify, session
from . import imb
from . import config
import pdfkit
from . import usps_api
from . import app
import datetime
import redis

ROLLING_WINDOW = 50

redis_client = redis.Redis(host='localhost', port=6379, db=0)
def generate_serial():
    today = datetime.datetime.today()
    num_days = (today - datetime.datetime(1970,1,1)).days
    base = num_days % ROLLING_WINDOW
    day_key = "serial_" + str(base)
    perday_counter = redis_client.incr(day_key)
    if perday_counter >= 9999:
        raise ValueError
    redis_client.expire(day_key, 48 * 60 * 60)
    return base * 10000 + int(perday_counter)

def generate_human_readable(receipt_zip: int, serial: int):
    return "{0:02d}-{1:03d}-{2:d}-{3:06d}-{4:d}".format(config.BARCODE_ID, config.SRV_TYPE, config.MAILER_ID, serial, receipt_zip)

def query_usps_tracking(receipt_zip: int, serial: int):
    imb = generate_human_readable(receipt_zip, serial)
    imb = imb.replace('-', '')
    return usps_api.get_piece_tracking(imb)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    sender_address = request.form['sender_address']
    recipient_name = request.form['recipient_name']
    recipient_company = request.form.get('recipient_company', '')
    recipient_street = request.form['recipient_street']
    recipient_address2 = request.form.get('recipient_address2', '')
    recipient_city = request.form['recipient_city']
    recipient_state = request.form['recipient_state']
    try:
        recipient_zip = int(request.form['recipient_zip'])
    except:
        response = "Serial number or receipt zip is not number!"
        return response
    recipient_address_parts = [
        recipient_name,
        recipient_company,
        recipient_street,
        recipient_address2,
        f"{recipient_city}, {recipient_state}, {request.form['recipient_zip']}"
    ]
    recipient_address = '\n'.join(filter(bool, recipient_address_parts))
    serial = generate_serial()
    session['sender_address'] = sender_address
    session['recipient_address'] = recipient_address
    session['serial'] = serial
    session['recipient_zip'] = recipient_zip
    return render_template('generate.html', serial=serial, recipient_zip=recipient_zip)

@app.route('/download/<type>')
def download(type: str):
    sender_address = session['sender_address']
    recipient_address = session['recipient_address']
    serial = session['serial']
    recipient_zip = session['recipient_zip']
    html = render_template('envelopepdf.html', sender_address=sender_address, recipient_address=recipient_address, 
                           human_readable_bar=generate_human_readable(recipient_zip, serial), 
                           barcode=imb.encode(config.BARCODE_ID, config.SRV_TYPE, config.MAILER_ID, serial, str(recipient_zip)))
    if type == 'html':
        return html
    elif type == 'pdf':
        options={
            'page-height': '4.125in',
            'page-width': '9.5in',
            'margin-bottom' : '0in',
            'margin-top': '0in',
            'margin-left': '0in',
            'margin-right': '0in',
            'disable-smart-shrinking': '',
        }
        pdf = pdfkit.from_string(html, False, options=options)
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename=envelope.pdf'
        return response
    else:
        return "Type not valid"

@app.route('/track', methods=['POST'])
def track():
    try:
        receipt_zip = int(request.form['receipt_zip'])
        serial = int(request.form['serial'])
    except:
        response = "Serial number or receipt zip is not number!"
        return response
    result = query_usps_tracking(receipt_zip, serial)
    if 'error' in result:
        message = "{}: {}. Details: {}".format(result['error'], result['error_description'], result['details'])
        return render_template("tracking.html", error_message=message)
    elif 'message' in result and result['message']:
        return render_template("tracking.html", error_message=result['message'])
    else:
        return render_template("tracking.html", data=result['data'])

