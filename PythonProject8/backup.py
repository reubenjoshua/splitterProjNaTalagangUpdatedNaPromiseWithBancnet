from flask import Flask, request, jsonify, send_file, Response, stream_with_context, make_response, send_from_directory
from flask_cors import CORS
import pandas as pd
import io
import re
from datetime import datetime
import zipfile
import os
import logging
from collections import Counter
import werkzeug
from werkzeug.serving import make_server
from werkzeug.middleware.proxy_fix import ProxyFix
import signal
import sys
import threading
import queue
import json
import uuid
from io import BytesIO
import csv
import tempfile
import shutil
import traceback
import socket
from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get the absolute path to the project root directory
project_root = os.path.abspath(os.path.dirname(__file__))
static_folder = os.path.join(project_root, 'dist')

app = Flask(__name__,
            static_folder=static_folder,
            static_url_path='')
app.wsgi_app = ProxyFix(app.wsgi_app)
CORS(app, resources={r"/*": {"origins": "*"}})  # Allow all origins

# Configure upload folder
UPLOAD_FOLDER = os.path.join(project_root, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Increase the maximum content length to 1GB
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB in bytes

# Increase the timeout to 30 minutes
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 1800  # 30 minutes

# Disable signal handling that might cause abortions
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)

# Create a queue for processing results
processing_queue = queue.Queue()

# Store processing status and results
processing_status = {}
processing_results = {}

# Define payment modes and their variations
PAYMENT_MODES = [
    {
        'name': 'BayadCenter',
        'variations': ['BAYAD', 'BAYADCENTER', 'BYC', 'BAYAD CENTER'],
        'mappings': ['BAYAD', 'BAYADCENTER', 'BYC', 'BAYAD CENTER']
    },
    {
        'name': 'BDO',
        'variations': ['BDO', 'BANCO DE ORO'],
        'mappings': ['BDO', 'BANCO DE ORO']
    },
    {
        'name': 'PNB',
        'variations': ['PNB', 'PHILIPPINE NATIONAL BANK'],
        'mappings': ['PNB', 'PHILIPPINE NATIONAL BANK']
    },
    {
        'name': 'Cebuana',
        'variations': ['CEBUANA', 'CEBUANA LHUILLIER', 'CEBUANA LHUILIER'],
        'mappings': ['CEBUANA', 'CEBUANA LHUILLIER', 'CEBUANA LHUILIER']
    },
    {
        'name': 'Chinabank',
        'variations': ['CHINABANK', 'CHINA BANK', 'CHINA SAVINGS BANK'],
        'mappings': ['CHINABANK', 'CHINA BANK', 'CHINA SAVINGS BANK']
    },
    {
        'name': 'CIS',
        'variations': ['CIS', 'CIS BAYAD'],
        'mappings': ['CIS', 'CIS BAYAD']
    },
    {
        'name': 'Metrobank',
        'variations': ['METROBANK', 'METRO', 'METRO BANK'],
        'mappings': ['METROBANK', 'METRO', 'METRO BANK']
    },
    {
        'name': 'Unionbank',
        'variations': ['UNIONBANK', 'UNION BANK', 'UNION BANK OF THE PHILIPPINES'],
        'mappings': ['UNIONBANK', 'UNION BANK', 'UNION BANK OF THE PHILIPPINES']
    },
    {
        'name': 'ECPAY',
        'variations': ['ECPAY', 'EC PAY'],
        'mappings': ['G-XCHANGE INC (MYNT)', 'G-XCHANGE', 'MYNT', 'ECPAY', 'EC PAY']
    },
    {
        'name': 'PERALINK',
        'variations': ['PERALINK', 'PERA LINK'],
        'mappings': ['PERALINK', 'PERA LINK']
    },
    {
        'name': 'SM',
        'variations': ['SM', 'SM STORE', 'SM SUPERMARKET'],
        'mappings': ['SM', 'SM STORE', 'SM SUPERMARKET']
    },
    {
        'name': 'BANCNET',
        'variations': ['BANCNET', 'BANC NET'],
        'mappings': ['BANCNET', 'BANC NET']
    }
]


def detect_payment_mode(row):
    """Detect payment mode from a row of data"""
    # First, check the Name & Remarks field (first column)
    if row[0]:
        name_field = row[0].strip().upper()

        # Check for exact matches in mappings first
        for mode in PAYMENT_MODES:
            if any(mapping.upper() in name_field for mapping in mode['mappings']):
                return mode['name']

        # If no exact match, check for variations
        for mode in PAYMENT_MODES:
            if any(variation in name_field for variation in mode['variations']):
                return mode['name']

    # If not found in Name & Remarks, check other columns
    for i in range(1, len(row)):
        cell = row[i].strip().upper()

        # Skip cells that are ATM references or dates
        if re.match(r'^\d{14}$', cell) or re.match(r'^\d{4}-\d{2}-\d{2}$', cell) or re.match(r'^\d{2}/\d{2}/\d{4}$',
                                                                                             cell):
            continue

        # Check for payment mode variations
        for mode in PAYMENT_MODES:
            if any(variation in cell for variation in mode['variations']):
                return mode['name']

    # If still not found, check for payment mode in the raw row content
    for cell in row:
        cell = cell.strip().upper()
        for mode in PAYMENT_MODES:
            if any(variation in cell for variation in mode['variations']):
                return mode['name']

    return 'Unknown'


def detect_amount(row):
    """Detect amount from a row of data"""
    # Debug the incoming row
    logger.debug(f"\nAttempting to detect amount in row: {row}")

    # First try to find amount in the original line
    original_line = ' '.join(str(x) for x in row)
    logger.debug(f"Checking full line: {original_line}")

    # Look for numbers with 1, 2, or 4 decimal places, with or without commas
    amount_patterns = [
        (r'\b\d{1,3}(?:,\d{3})*\.\d{4}\b', 'with commas four decimals'),  # matches 1,234.5678
        (r'\b\d{1,3}(?:,\d{3})*\.\d{2}\b', 'with commas two decimals'),  # matches 1,234.56
        (r'\b\d{1,3}(?:,\d{3})*\.\d\b', 'with commas one decimal'),  # matches 1,234.5
        (r'\b\d+\.\d{4}\b', 'four decimals'),  # matches 123.5678
        (r'\b\d+\.\d{2}\b', 'two decimals'),  # matches 123.45
        (r'\b\d+\.\d\b', 'one decimal')  # matches 123.4
    ]

    # First check the full line
    for pattern, pattern_type in amount_patterns:
        matches = re.finditer(pattern, original_line)
        for match in matches:
            try:
                amount_str = match.group(0)
                # Remove commas and handle decimals
                amount_str = amount_str.replace(',', '')
                # If it has 4 decimal places, round to 2
                if len(amount_str.split('.')[1]) == 4:
                    amount = round(float(amount_str), 2)
                # If it has 1 decimal place, add a zero
                elif len(amount_str.split('.')[1]) == 1:
                    amount = float(amount_str + '0')
                else:
                    amount = float(amount_str)

                if 0 < amount < 1000000000:  # Basic sanity check
                    logger.debug(f"Found amount {amount:.2f} in full line using {pattern_type}")
                    return amount
            except ValueError as e:
                logger.debug(f"Failed to convert {match.group(0)} to float: {e}")

    # If no amount found in full line, check individual cells
    logger.debug("No amount found in full line, checking individual cells...")

    for i, cell in enumerate(row):
        if not isinstance(cell, str):
            continue

        clean_value = cell.strip()
        logger.debug(f"Checking cell {i}: {clean_value}")

        # Skip empty cells
        if not clean_value:
            continue

        # Skip cells that look like dates or ATM references
        if (re.match(r'^\d{14}$', clean_value) or
                re.match(r'^\d{4}-\d{2}-\d{2}$', clean_value) or
                re.match(r'^\d{2}/\d{2}/\d{4}$', clean_value)):
            logger.debug(f"Skipping cell {i} - looks like date or reference")
            continue

        # Check for decimal formats with or without commas
        for pattern, pattern_type in [
            (r'^\d{1,3}(?:,\d{3})*\.\d{4}$', 'with commas four decimals'),  # matches 1,234.5678
            (r'^\d{1,3}(?:,\d{3})*\.\d{2}$', 'with commas two decimals'),  # matches 1,234.56
            (r'^\d{1,3}(?:,\d{3})*\.\d$', 'with commas one decimal'),  # matches 1,234.5
            (r'^\d+\.\d{4}$', 'four decimals'),  # matches 123.5678
            (r'^\d+\.\d{2}$', 'two decimals'),  # matches 123.45
            (r'^\d+\.\d$', 'one decimal')  # matches 123.4
        ]:
            if re.match(pattern, clean_value):
                try:
                    # Remove commas and handle decimals
                    clean_value = clean_value.replace(',', '')
                    # If it has 4 decimal places, round to 2
                    if len(clean_value.split('.')[1]) == 4:
                        amount = round(float(clean_value), 2)
                    # If it has 1 decimal place, add a zero
                    elif len(clean_value.split('.')[1]) == 1:
                        amount = float(clean_value + '0')
                    else:
                        amount = float(clean_value)

                    if 0 < amount < 1000000000:  # Basic sanity check
                        logger.debug(f"Found amount {amount:.2f} in cell {i} using {pattern_type}")
                        return amount
                except ValueError as e:
                    logger.debug(f"Failed to convert {clean_value} to float: {e}")

    # If still no amount found, try a more lenient pattern
    for i, cell in enumerate(row):
        if not isinstance(cell, str):
            continue

        clean_value = cell.strip()

        # Try to find any number that looks like an amount
        if re.match(r'^[\d,]+\.\d{1,4}$', clean_value):
            try:
                # Remove commas and handle decimals
                clean_value = clean_value.replace(',', '')
                # If it has 4 decimal places, round to 2
                if len(clean_value.split('.')[1]) == 4:
                    amount = round(float(clean_value), 2)
                # If it has 1 decimal place, add a zero
                elif len(clean_value.split('.')[1]) == 1:
                    amount = float(clean_value + '0')
                else:
                    amount = float(clean_value)

                if 0 < amount < 1000000000:  # Basic sanity check
                    logger.debug(f"Found amount {amount:.2f} in cell {i} using lenient pattern")
                    return amount
            except ValueError as e:
                logger.debug(f"Failed to convert {clean_value} to float: {e}")

    logger.debug("No valid amount found in any cell")
    return 0


def detect_date(row):
    """Detect date from a row of data"""
    for cell in row:
        # Check for YYYY-MM-DD format
        if re.match(r'^\d{4}-\d{2}-\d{2}$', cell.strip()):
            return cell.strip()
        # Check for MM/DD/YYYY format
        if re.match(r'^\d{2}/\d{2}/\d{4}$', cell.strip()):
            return cell.strip()
    return ''


def detect_separator(line):
    """Detect the separator used in the line"""
    # Count occurrences of each separator
    pipe_count = line.count('|')
    caret_count = line.count('^')
    comma_count = line.count(',')

    # Check for consistent spacing that might indicate fixed-width
    space_groups = len([m for m in re.finditer(r'\s{2,}', line)])

    # Determine the most likely separator
    separators = {
        '|': pipe_count,
        '^': caret_count,
        ',': comma_count,
        'fixed-width': space_groups
    }

    # Get the separator with the highest count
    max_separator = max(separators.items(), key=lambda x: x[1])

    # If we found a clear separator, return it
    if max_separator[1] > 0:
        return max_separator[0]

    # Default to fixed-width if no clear separator is found
    return 'fixed-width'


def parse_fixed_width_line(line):
    """Parse a fixed-width line into fields"""
    # First try to split by multiple spaces
    parts = [part for part in re.split(r'\s+', line) if part.strip()]

    # If we found any parts, process them
    if parts:
        # Check if any part looks like an amount
        amount_parts = []
        other_parts = []

        for part in parts:
            # Check if part matches amount pattern
            if re.match(r'^[P₱]?\d+(?:\.\d{1,2})?$', part.strip()):
                amount_parts.append(part)
            else:
                other_parts.append(part)

        # Combine the parts, putting amounts first
        return amount_parts + other_parts

    return []


def detect_atm_reference_by_payment_mode(fields, payment_mode, original_line):
    """
    Detect ATM reference based on the payment mode
    """
    try:
        if payment_mode == 'METROBANK':
            # For METROBANK, split by spaces and get index 1
            fields = [f.strip() for f in original_line.split() if f.strip()]
            if len(fields) > 1:
                atm_ref = fields[1].strip()
                logger.debug(f"Found METROBANK ATM ref: {atm_ref} from field: {fields[1]}")
                return atm_ref
            return None

        elif payment_mode == 'PNB':
            # For PNB, ATM ref is in field 5 (index 4)
            if len(fields) > 4:
                atm_ref_field = fields[4].strip()
                logger.debug(f"PNB ATM ref field: {atm_ref_field}")

                # Clean the reference (keep only digits)
                clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())

                # Take first 4 digits as ATM ref
                if len(clean_ref) >= 4:
                    atm_ref = clean_ref[:4]
                    logger.debug(f"Found PNB ATM ref: {atm_ref} from {atm_ref_field}")
                    return atm_ref
            return None

        elif payment_mode == 'BDO':
            # For BDO, ATM ref is in field 6 (index 5)
            if len(fields) > 5:
                atm_ref_field = fields[5].strip()
                # Clean the reference (keep only digits)
                clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                # Take first 4 digits as ATM ref
                if len(clean_ref) >= 4:
                    atm_ref = clean_ref[:4]
                    logger.debug(f"Found BDO ATM ref: {atm_ref} from {atm_ref_field}")
                    return atm_ref
            return None

        elif payment_mode == 'ECPAY':
            # For ECPAY, ATM ref is in field 6 (index 5)
            if len(fields) > 5:
                atm_ref_field = fields[5].strip()
                # Clean the reference (keep only digits)
                clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                # Take first 4 digits as ATM ref
                if len(clean_ref) >= 4:
                    atm_ref = clean_ref[:4]
                    logger.debug(f"Found ECPAY ATM ref: {atm_ref} from {atm_ref_field}")
                    return atm_ref
            return None

        elif payment_mode == 'UNIONBANK':
            # For UNIONBANK, ATM ref is at the end of the line
            # Find the last sequence of 14 digits in the line
            matches = re.findall(r'\d{14}', original_line)
            if matches:
                atm_ref_field = matches[-1]  # Take the last match
                # Take first 4 digits as ATM ref
                atm_ref = atm_ref_field[:4]
                logger.debug(f"Found UNIONBANK ATM ref: {atm_ref} from {atm_ref_field}")
                return atm_ref
            return None

        elif payment_mode == 'CIS':
            # For CIS, ATM ref is in field 2 (index 1)
            if len(fields) > 1:
                atm_ref_field = fields[1].strip()
                # Clean the reference (keep only digits)
                clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                # Take first 4 digits as ATM ref
                if len(clean_ref) >= 4:
                    atm_ref = clean_ref[:4]
                    logger.debug(f"Found CIS ATM ref: {atm_ref} from {atm_ref_field}")
                    return atm_ref
            return None

        elif payment_mode == 'CHINABANK':
            # For CHINABANK, ATM ref is in field 4 (index 3)
            if len(fields) > 3:
                atm_ref_field = fields[3].strip()
                # Clean the reference (keep only digits)
                clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                # Take first 4 digits as ATM ref
                if len(clean_ref) >= 4:
                    atm_ref = clean_ref[:4]
                    logger.debug(f"Found CHINABANK ATM ref: {atm_ref} from {atm_ref_field}")
                    return atm_ref
            return None

        elif payment_mode == 'CEBUANA':
            # For CEBUANA, ATM ref is in field 5 (index 4)
            if len(fields) > 4:
                atm_ref_field = fields[4].strip()
                # Clean the reference (keep only digits)
                clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                # Take first 4 digits as ATM ref
                if len(clean_ref) >= 4:
                    atm_ref = clean_ref[:4]
                    logger.debug(f"Found CEBUANA ATM ref: {atm_ref} from {atm_ref_field}")
                    return atm_ref
            return None

        return None

    except Exception as e:
        logger.error(f"Error detecting ATM reference: {str(e)}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return None


def detect_payment_mode_from_filename(filename):
    """Detect payment mode from filename"""
    # Convert filename to uppercase for case-insensitive comparison
    filename_upper = filename.upper()

    if 'ECPAY' in filename_upper:
        return 'ECPAY'
    elif 'BDO' in filename_upper:
        return 'BDO'
    elif 'CEBUANA' in filename_upper:
        return 'CEBUANA'
    elif 'PERALINK' in filename_upper:
        return 'PERALINK'
    elif 'CHINABANK' in filename_upper or 'CHINA BANK' in filename_upper:
        return 'CHINABANK'
    elif 'CIS' in filename_upper:
        return 'CIS'
    elif 'METROBANK' in filename_upper or 'METRO BANK' in filename_upper:
        return 'METROBANK'
    elif 'PNB' in filename_upper:
        return 'PNB'
    elif 'UB' in filename_upper or 'UNIONBANK' in filename_upper:
        return 'UNIONBANK'
    elif 'SM' in filename_upper:
        return 'SM'
    elif 'BANCNET' in filename_upper:
        return 'BANCNET'

    return 'Unknown'


def get_separator(content):
    """Determine the separator used in the file content"""
    # Count occurrences of each separator
    pipe_count = content.count('|')
    caret_count = content.count('^')
    comma_count = content.count(',')

    # Check for consistent spacing that might indicate fixed-width
    space_groups = len([m for m in re.finditer(r'\s{2,}', content)])

    # Determine the most likely separator
    separators = {
        '|': pipe_count,
        '^': caret_count,
        ',': comma_count,
        'fixed-width': space_groups
    }

    # Get the separator with the highest count
    max_separator = max(separators.items(), key=lambda x: x[1])

    # If we found a clear separator, return it
    if max_separator[1] > 0:
        return max_separator[0]

    # Default to fixed-width if no clear separator is found
    return 'fixed-width'


def extract_amount(fields, payment_mode):
    """Extract amount from fields based on payment mode"""
    try:
        if payment_mode == 'BDO':
            # For BDO, amount is at index 9
            if len(fields) > 9:
                return float(fields[9].replace(',', ''))
        elif payment_mode == 'CHINABANK':
            # For CHINABANK, amount is at index 2
            if len(fields) > 2:
                return float(fields[2].replace(',', ''))
        elif payment_mode in ['CEBUANA', 'PERALINK']:
            # For CEBUANA and PERALINK, amount is at index 5
            if len(fields) > 5:
                return float(fields[5].replace(',', ''))
        else:
            # For other payment modes (like ECPAY), find the amount field
            for field in fields:
                # Look for decimal number pattern (e.g., 170.0, 1621.4)
                if re.match(r'^\d+\.\d+$', field.strip()):
                    return float(field.strip())

        # If no specific rule matched, try to find any amount in the fields
        for field in fields:
            # Remove currency symbols and commas
            clean_field = field.replace('₱', '').replace('P', '').replace(',', '').strip()
            try:
                amount = float(clean_field)
                if 0 < amount < 1000000000:  # Basic sanity check
                    return amount
            except ValueError:
                continue

        return 0.0
    except (ValueError, IndexError) as e:
        logger.error(f"Error extracting amount: {str(e)}")
        return 0.0


@app.route('/api/generate-report', methods=['POST'])
def generate_report():
    try:
        app.logger.info("Starting report generation")
        data = request.get_json()

        if not data or not isinstance(data, dict):
            raise ValueError("Invalid data format received")

        processed_data = data.get('processed_data', {})
        raw_contents = data.get('raw_contents', [])
        original_filename = data.get('original_filename', 'transactions')
        area = data.get('area', '')  # Get the area from the request

        # Log the received data for debugging
        app.logger.info(f"Received data - original_filename: {original_filename}, area: {area}")

        # Create a temporary directory for the files
        temp_dir = tempfile.mkdtemp()

        try:
            # Create CSV summary file
            csv_file_path = os.path.join(temp_dir, 'transactions_summary.csv')
            with open(csv_file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['OVERALL SUMMARY REPORT'])
                writer.writerow([])

                # Calculate totals
                total_transactions = 0
                total_amount = 0.0

                # Process transactions
                for atm_ref, transactions in processed_data.items():
                    if not isinstance(transactions, list):
                        continue

                    total_transactions += len(transactions)
                    for trans in transactions:
                        if isinstance(trans, dict):
                            payment_mode = trans.get('payment_mode', '')
                            original_line = trans.get('original_line', '')

                            if payment_mode == 'METROBANK' and original_line:
                                # For METROBANK, extract amount from the line
                                amount_match = re.search(r'(\d{11,12})[A-Z]', original_line)
                                if amount_match:
                                    amount_str = amount_match.group(1)
                                    amount = float(amount_str) / 100
                                    total_amount += amount
                                    logger.debug(f"Adding METROBANK amount to total: {amount}")
                            elif payment_mode == 'SM' and original_line:
                                # Initialize group_total and dates for SM transactions
                                if 'group_total' not in locals():
                                    group_total = 0.0
                                if 'dates' not in locals():
                                    dates = set()

                                # For SM, extract amount from the line
                                cs_pos = original_line.find('CS')
                                if cs_pos > 0:
                                    # Look backwards from CS to find the amount
                                    amount_str = ''
                                    for i in range(cs_pos - 1, max(0, cs_pos - 10), -1):
                                        if original_line[i].isdigit():
                                            amount_str = original_line[i] + amount_str
                                        else:
                                            break

                                    if amount_str:
                                        amount = float(amount_str) / 100
                                        group_total += amount
                                        total_amount += amount  # Add to total_amount as well
                                        logger.debug(f"Found SM amount for ATM {atm_ref}: {amount} from {amount_str}")

                                # Extract date from positions 3-11 (MMDDYYYY format)
                                if len(original_line) >= 11:
                                    date_str = original_line[3:11]
                                    if date_str:
                                        formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                        dates.add(f"{formatted_date}")
                                        logger.debug(f"Found SM date: {formatted_date} from {date_str}")
                            elif payment_mode == 'UNIONBANK' and original_line:
                                # Initialize group_total and dates for UNIONBANK transactions
                                if 'group_total' not in locals():
                                    group_total = 0.0
                                if 'dates' not in locals():
                                    dates = set()

                                # For UNIONBANK, extract amount from the line
                                amount_match = re.search(r'(\d{12})(?:DB|LC)\d*\s*$', original_line)
                                if amount_match:
                                    amount_str = amount_match.group(1)
                                    amount = float(amount_str) / 100
                                    group_total += amount
                                    total_amount += amount  # Add to total_amount as well
                                    logger.debug(f"Found UNIONBANK amount: {amount} from {amount_str}")

                                # Extract date that appears after UB followed by digits
                                date_match = re.search(r'UB\d+\s+(\d{6})', original_line)
                                if date_match:
                                    date_str = date_match.group(1)
                                    logger.debug(f"Raw date string from UNIONBANK line: {date_str}")
                                    formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                    dates.add(f"{formatted_date}")
                                    logger.debug(f"Formatted UNIONBANK date: {formatted_date} from {date_str}")
                            else:
                                amount = trans.get('amount', 0)
                                if isinstance(amount, (int, float)):
                                    total_amount += float(amount)

                # Write totals
                writer.writerow(['Total Transactions', total_transactions])
                writer.writerow(['Total Amount', f'₱{total_amount:,.2f}'])
                writer.writerow([])

                # Write ATM breakdown
                writer.writerow(['ATM REFERENCE BREAKDOWN'])
                writer.writerow(['ATM Reference', 'Count', 'Amount', 'PaymentMode', 'Dates'])

                # Process each ATM reference group
                for atm_ref, transactions in processed_data.items():
                    if not isinstance(transactions, list):
                        continue

                    group_total = 0.0  # Initialize group_total here
                    dates = set()  # Initialize dates set here
                    payment_mode = None  # Initialize payment_mode

                    # Process each transaction
                    for trans in transactions:
                        if isinstance(trans, dict):
                            payment_mode = trans.get('payment_mode', '')
                            original_line = trans.get('original_line', '')
                            raw_row = trans.get('raw_row', [])

                            # Calculate amount based on payment mode
                            if payment_mode == 'BANCNET' and original_line:
                                # For BANCNET, get the ATM reference from the transaction object
                                atm_ref = trans.get('atm_reference', '')
                                if not atm_ref:
                                    # If not in transaction object, extract from line
                                    asterisk_pos = original_line.find('*')
                                    if asterisk_pos > 0:
                                        atm_ref = original_line[asterisk_pos - 14:asterisk_pos]

                                # Extract amount from the line
                                last_asterisk_pos = original_line.rfind('*')
                                if last_asterisk_pos > 0 and len(original_line) > last_asterisk_pos + 28:
                                    # Get the 8 digits after the first 20 characters following the asterisk
                                    amount_str = original_line[last_asterisk_pos + 21:last_asterisk_pos + 29]
                                    logger.debug(f'BANCNET - Amount string from positions after first 20 chars: {amount_str}')

                                    try:
                                        # Convert to float and divide by 100 to get the correct decimal place
                                        amount = float(amount_str) / 100
                                        if 0 < amount < 1000000:
                                            logger.debug(f'Found BANCNET amount {amount} from {amount_str}')
                                            group_total += amount  # Use group_total instead of grouped_data
                                    except ValueError as e:
                                        logger.error(f'Error converting BANCNET amount: {amount_str}, error: {str(e)}')

                                # Extract date from the first 20 characters
                                if len(original_line) >= 20:
                                    first_20 = original_line[:20]
                                    # Extract last 6 digits for date (YYMMDD format)
                                    date_str = first_20[-6:]
                                    try:
                                        # Format as MM/DD/20YY
                                        yy = date_str[:2]
                                        mm = date_str[2:4]
                                        dd = date_str[4:]
                                        formatted_date = f"{mm}/{dd}/20{yy}"
                                        dates.add(formatted_date)
                                        logger.debug(f'Added BANCNET date {formatted_date} to transaction summary')
                                    except Exception as e:
                                        logger.error(f'Error formatting BANCNET date: {date_str}, error: {str(e)}')

                            elif payment_mode == 'SM' and original_line:
                                # Initialize group_total and dates for SM transactions
                                if 'group_total' not in locals():
                                    group_total = 0.0
                                if 'dates' not in locals():
                                    dates = set()

                                # For SM, extract amount from the line
                                cs_pos = original_line.find('CS')
                                if cs_pos > 0:
                                    # Look backwards from CS to find the amount
                                    amount_str = ''
                                    for i in range(cs_pos - 1, max(0, cs_pos - 10), -1):
                                        if original_line[i].isdigit():
                                            amount_str = original_line[i] + amount_str
                                        else:
                                            break

                                    if amount_str:
                                        amount = float(amount_str) / 100
                                        group_total += amount
                                        total_amount += amount  # Add to total_amount as well
                                        logger.debug(f"Found SM amount for ATM {atm_ref}: {amount} from {amount_str}")

                                # Extract date from positions 3-11 (MMDDYYYY format)
                                if len(original_line) >= 11:
                                    date_str = original_line[3:11]
                                    if date_str:
                                        formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                        dates.add(f"{formatted_date}")
                                        logger.debug(f"Found SM date: {formatted_date} from {date_str}")
                            elif payment_mode == 'METROBANK' and original_line:
                                # For METROBANK, extract amount from the line
                                amount_match = re.search(r'(\d{11,12})[A-Z]', original_line)
                                if amount_match:
                                    amount_str = amount_match.group(1)
                                    amount = float(amount_str) / 100
                                    group_total += amount
                                    logger.debug(f"Found METROBANK amount: {amount} from {amount_str}")

                                # Extract date from the last field of the line
                                fields = original_line.split()
                                if fields:  # Check if we have any fields
                                    last_field = fields[-1]  # Get the last field

                                    # First try to find a 6-digit date at the start of the field
                                    if len(last_field) >= 6 and last_field[:6].isdigit():
                                        date_str = last_field[:6]
                                    # If not found at start, try to find it at the end
                                    elif len(last_field) >= 6 and last_field[-6:].isdigit():
                                        date_str = last_field[-6:]
                                    else:
                                        continue  # Skip if no valid date found

                                    formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                    dates.add(f"{formatted_date}")
                                    logger.debug(f"Found METROBANK date: {formatted_date} from {date_str}")
                            elif payment_mode == 'UNIONBANK' and original_line:
                                # For UNIONBANK, extract amount from the line
                                amount_match = re.search(r'(\d{12})(?:DB|LC)\d*\s*$', original_line)
                                if amount_match:
                                    amount_str = amount_match.group(1)
                                    amount = float(amount_str) / 100
                                    group_total += amount
                                    logger.debug(f"Found UNIONBANK amount: {amount} from {amount_str}")

                                # Extract date that appears after UB followed by digits
                                date_match = re.search(r'UB\d+\s+(\d{6})', original_line)
                                if date_match:
                                    date_str = date_match.group(1)
                                    logger.debug(f"Raw date string from UNIONBANK line: {date_str}")
                                    formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                    dates.add(f"{formatted_date}")
                                    logger.debug(f"Formatted UNIONBANK date: {formatted_date} from {date_str}")
                            else:
                                amount = trans.get('amount', 0)
                                if isinstance(amount, (int, float)):
                                    group_total += float(amount)

                                # Handle dates for other payment modes
                                if payment_mode == 'BDO' and len(raw_row) > 2:
                                    date_str = raw_row[2].strip()
                                    if date_str:
                                        dates.add(f"{date_str}")
                                elif payment_mode == 'CEBUANA' and len(raw_row) > 2:
                                    date = raw_row[2].strip()
                                    if date:
                                        dates.add(date)
                                elif payment_mode == 'PNB' and len(raw_row) > 1:
                                    date_str = raw_row[1].strip()
                                    if date_str:
                                        dates.add(f"{date_str}")
                                elif payment_mode == 'CIS' and len(raw_row) > 0:
                                    date_str = raw_row[0].strip()
                                    if date_str:
                                        formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                        dates.add(f"{formatted_date}")
                                elif payment_mode == 'ECPAY' and len(raw_row) > 2:
                                    date_str = raw_row[2].strip()
                                    if date_str:
                                        dates.add(f"{date_str}")
                                elif payment_mode == 'CHINABANK' and len(raw_row) > 0:
                                    date_str = raw_row[0].strip()
                                    if date_str:
                                        formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                        dates.add(f"{formatted_date}")

                    # Convert dates set to sorted list without payment mode prefix
                    sorted_dates = [date for date in sorted(list(dates))]

                    # Write row with dates and group total
                    writer.writerow([
                        atm_ref,
                        len(transactions),
                        f'{group_total:,.2f}',
                        payment_mode if payment_mode else 'Unknown',
                        ', '.join(sorted_dates) if sorted_dates else ''
                    ])

            # Create individual ATM reports
            for atm_ref, transactions in processed_data.items():
                if not isinstance(transactions, list):
                    continue

                report_path = os.path.join(temp_dir, f'ATM_{atm_ref}_{payment_mode}_{area}.txt')

                with open(report_path, 'w', encoding='utf-8') as f:
                    # Write only raw transaction lines
                    if isinstance(transactions, list):
                        for trans in transactions:
                            if isinstance(trans, dict) and 'original_line' in trans:
                                f.write(f'{trans["original_line"]}\n')
                            elif isinstance(trans, str):
                                f.write(f'{trans}\n')
                            elif isinstance(trans, dict) and 'raw_contents' in trans:
                                for line in trans['raw_contents']:
                                    f.write(f'{line}\n')

            # Create zip file with area appended to filename
            zip_path = os.path.join(temp_dir, f'{original_filename}_{area}.zip')
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                # Add all files except the zip itself
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        if file != f'{original_filename}_{area}.zip':
                            file_path = os.path.join(root, file)
                            arc_name = os.path.basename(file_path)
                            zipf.write(file_path, arc_name)

            # Read zip file
            with open(zip_path, 'rb') as f:
                zip_data = f.read()

            # Create response with area appended to filename
            response = make_response(zip_data)
            response.headers['Content-Type'] = 'application/zip'
            response.headers['Content-Disposition'] = f'attachment; filename="{original_filename}_{area}.zip"'

            # Log the final filename for debugging
            app.logger.info(f"Generated zip file: {original_filename}_{area}.zip")

            return response

        finally:
            # Clean up
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up temp directory: {cleanup_error}")

    except Exception as e:
        logger.error(f"Error generating report: {str(e)}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


@app.route('/')
def serve():
    """Serve the React app"""
    try:
        return send_from_directory(app.static_folder, 'index.html')
    except Exception as e:
        logger.error(f"Error serving index.html: {str(e)}")
        return jsonify({'error': 'Could not serve the application'}), 500


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files from the dist folder"""
    try:
        return send_from_directory(app.static_folder, path)
    except Exception as e:
        logger.error(f"Error serving static file {path}: {str(e)}")
        return jsonify({'error': 'Could not serve the file'}), 404


@app.route('/api/health')
def health_check():
    return jsonify({'status': 'healthy'})


def process_file_in_thread(file_content, filename, processing_id):
    """Process file in a separate thread"""
    try:
        # Update status to processing
        processing_status[processing_id] = {
            'status': 'processing',
            'progress': 0,
            'error': None
        }

        # Log the start of processing
        logger.info(f"Starting to process file: {filename}")
        logger.debug(f"File content length: {len(file_content)}")
        logger.debug(f"First few lines of content: {file_content[:500]}")

        # Process the file
        result = process_file_content(file_content, filename)

        # Store results
        processing_results[processing_id] = result

        # Update status to completed
        processing_status[processing_id] = {
            'status': 'completed',
            'progress': 100,
            'error': None
        }

        logger.info(f"Successfully processed file: {filename}")
        logger.debug(f"Processed {result.get('total_transactions', 0)} transactions")

    except Exception as e:
        # Log the full error details
        error_details = traceback.format_exc()
        logger.error(f"Error processing file: {str(e)}")
        logger.error(f"Error details:\n{error_details}")

        # Update status with detailed error
        processing_status[processing_id] = {
            'status': 'error',
            'progress': 0,
            'error': f"Error processing file: {str(e)}\nDetails: {error_details}"
        }


@app.route('/api/upload-file', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    payment_mode = request.form.get('payment_mode')
    if not payment_mode:
        return jsonify({'error': 'No payment mode selected'}), 400

    area = request.form.get('area')
    if not area:
        return jsonify({'error': 'No area selected'}), 400

    valid_payment_modes = {
        'BDO', 'CEBUANA', 'CHINABANK', 'ECPAY',
        'METROBANK', 'UNIONBANK', 'SM', 'PNB', 'CIS', 'BANCNET'
    }

    if payment_mode.upper() not in {mode.upper() for mode in valid_payment_modes}:
        return jsonify({'error': f'Invalid payment mode: {payment_mode}'}), 400

    valid_areas = {'EPR', 'PIC', 'FPR'}
    if area not in valid_areas:
        return jsonify({'error': f'Invalid area: {area}'}), 400

    try:
        # Create a unique processing ID
        processing_id = str(uuid.uuid4())

        # Get the original filename and extension
        original_filename = secure_filename(file.filename)
        name, ext = os.path.splitext(original_filename)

        # Create new filename with area appended
        new_filename = f"{name}_{area}{ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)

        # Save the file with the new filename
        file.save(file_path)

        # Store the payment mode and area in the processing status
        processing_status[processing_id] = {
            'status': 'processing',
            'payment_mode': payment_mode,
            'area': area,
            'file_path': file_path
        }

        # Start processing the file in a background thread
        thread = threading.Thread(
            target=process_file,
            args=(processing_id, file_path, payment_mode)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'message': 'File uploaded successfully',
            'processing_id': processing_id
        })
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return jsonify({'error': str(e)}), 500


def process_file(processing_id, file_path, payment_mode):
    try:
        logger.info(f"Starting to process file: {file_path}")
        logger.info(f"Payment mode: {payment_mode}")

        # Try different encodings to read the file
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        content = None

        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                logger.info(f"Successfully read file using {encoding} encoding")
                break
            except UnicodeDecodeError:
                logger.warning(f"Failed to read file using {encoding} encoding")
                continue

        if content is None:
            raise Exception("Could not read file with any of the supported encodings")

        # Process the file content based on the payment mode
        processed_data = process_file_content(content, payment_mode)

        # Store the results in processing_results
        processing_results[processing_id] = {
            'processed_data': processed_data,
            'raw_contents': content.split('\n'),
            'separator': get_separator(content),
            'payment_mode': payment_mode,
            'grouped_data': processed_data.get('grouped_data', {})
        }

        # Update the processing status
        processing_status[processing_id] = {
            'status': 'completed',
            'processed_data': processed_data,
            'raw_contents': content.split('\n'),
            'separator': get_separator(content),
            'payment_mode': payment_mode,
            'grouped_data': processed_data.get('grouped_data', {})
        }

        logger.info(f"File processing completed: {file_path}")
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        processing_status[processing_id] = {
            'status': 'error',
            'error': str(e)
        }


@app.route('/api/processing-status/<processing_id>', methods=['GET'])
def get_processing_status(processing_id):
    if processing_id not in processing_status:
        return jsonify({'error': 'Processing ID not found'}), 404

    status = processing_status[processing_id]

    if status['status'] == 'completed':
        # Get the results from processing
        results = processing_results[processing_id]

        # Convert the grouped data into the expected format
        processed_data = {}
        raw_contents = []

        # Calculate total amount from backend data
        backend_total = 0
        total_transactions = 0
        total_bancnet_amount = 0.0  # Initialize BANCNET total amount
        grouped_data = results.get('grouped_data', {})

        # Process the grouped data
        for atm_ref, data in grouped_data.items():
            if not isinstance(data, dict):
                continue

            # Create an entry for each transaction in raw_contents
            transactions = []

            # Add all raw contents to the list first
            raw_contents.extend(data.get('raw_contents', []))

            # Get the payment mode
            payment_mode = data.get('payment_mode', 'Unknown')

            # For METROBANK, use the total amount already calculated
            if payment_mode == 'METROBANK':
                transaction_count = data.get('transaction_count', 0)
                total_transactions += transaction_count
                backend_total += data.get('total_amount', 0)  # Add the pre-calculated total

                # Create one transaction object per raw content line
                for line in data.get('raw_contents', []):
                    # Extract amount from index 3 if it's followed by letters
                    amount = 0
                    fields = [f.strip() for f in line.split() if f.strip()]
                    if len(fields) > 3:
                        amount_field = fields[3].strip()
                        # Check if the field contains digits followed by letters
                        amount_match = re.match(r'^(\d+)[A-Z]', amount_field)
                        if amount_match:
                            amount_str = amount_match.group(1)
                            amount = float(amount_str) / 100
                            grouped_data[atm_ref]['total_amount'] += amount
                            logger.debug(f"Found METROBANK amount: {amount} from {amount_str}")

                    transaction = {
                        'payment_mode': payment_mode,
                        'amount': amount,
                        'raw_row': [line],
                        'original_line': line,
                        'display_ref': atm_ref,
                        'group_ref': atm_ref
                    }
                    transactions.append(transaction)

            elif payment_mode == 'BANCNET':
                transaction_count = data.get('transaction_count', 0)
                total_transactions += transaction_count
                backend_total += data.get('total_amount', 0)  # Add the pre-calculated total

                # Create one transaction object per raw content line
                for line in data.get('raw_contents', []):
                    # Extract amount from the line
                    amount = 0
                    last_asterisk_pos = line.rfind('*')
                    if last_asterisk_pos > 0 and len(line) > last_asterisk_pos + 28:
                        # Get the 8 digits after the first 20 characters following the asterisk
                        amount_str = line[last_asterisk_pos + 21:last_asterisk_pos + 29]
                        logger.debug(f'BANCNET - Amount string from positions after first 20 chars: {amount_str}')

                        try:
                            # Convert to float and divide by 100 to get the correct decimal place
                            amount = float(amount_str) / 100
                            if 0 < amount < 1000000:
                                logger.debug(f'Found BANCNET amount {amount} from {amount_str}')
                                total_bancnet_amount += amount  # Add to BANCNET total
                        except ValueError as e:
                            logger.error(f'Error converting BANCNET amount: {amount_str}, error: {str(e)}')

                    # Extract date from the first 20 characters
                    dates = set()
                    if len(line) >= 20:
                        first_20 = line[:20]
                        # Extract last 6 digits for date (YYMMDD format)
                        date_str = first_20[-6:]
                        try:
                            # Format as MM/DD/20YY
                            yy = date_str[:2]
                            mm = date_str[2:4]
                            dd = date_str[4:]
                            formatted_date = f"{mm}/{dd}/20{yy}"
                            dates.add(formatted_date)
                            logger.debug(f'Added BANCNET date {formatted_date} to transaction summary')
                        except Exception as e:
                            logger.error(f'Error formatting BANCNET date: {date_str}, error: {str(e)}')

                    transaction = {
                        'payment_mode': payment_mode,
                        'amount': amount,
                        'raw_row': [line],
                        'original_line': line,
                        'display_ref': atm_ref,
                        'group_ref': atm_ref,
                        'dates': list(dates)  # Include the dates in the transaction
                    }
                    transactions.append(transaction)

            elif payment_mode == 'SM':
                transaction_count = data.get('transaction_count', 0)
                total_transactions += transaction_count
                backend_total += data.get('total_amount', 0)

                # Create one transaction object per raw content line
                for line in data.get('raw_contents', []):
                    # Extract amount from the line
                    amount = 0
                    cs_pos = line.find('CS')
                    if cs_pos > 0:
                        # Look backwards from CS to find the amount
                        amount_str = ''
                        for i in range(cs_pos - 1, max(0, cs_pos - 10), -1):
                            if line[i].isdigit():
                                amount_str = line[i] + amount_str
                            else:
                                break

                        if amount_str:
                            amount = float(amount_str) / 100
                            backend_total += amount
                            logger.debug(f"Found SM amount: {amount} from {amount_str}")

                    # Extract ATM reference
                    atm_ref = line[18:31] if len(line) >= 45 else '0000'
                    first_four = atm_ref[:4]

                    transaction = {
                        'payment_mode': payment_mode,
                        'amount': amount,
                        'raw_row': [line],
                        'original_line': line,
                        'display_ref': first_four,
                        'group_ref': first_four
                    }
                    transactions.append(transaction)

            else:
                # Process each line to create transaction objects for other payment modes
                for line in data.get('raw_contents', []):
                    # Split line based on payment mode
                    if payment_mode == 'BDO':
                        fields = line.strip().split('|')
                    elif payment_mode == 'CHINABANK':
                        fields = [f for f in re.split(r'\s+', line.strip()) if f.strip()]
                    elif payment_mode in ['CIS', 'PNB']:
                        fields = [f.strip() for f in line.split('^')]
                    else:
                        fields = [f.strip() for f in line.split(',')]

                    # Extract amount based on payment mode
                    amount = 0
                    display_ref = None
                    group_ref = None

                    if payment_mode == 'PNB':
                        # For PNB, amount is at index 6
                        if len(fields) > 6:
                            try:
                                amount_str = fields[6].replace(',', '')
                                amount = float(amount_str)
                                backend_total += amount
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error converting PNB amount: {fields[6]}, error: {str(e)}")
                                amount = 0

                        # For PNB, handle ATM reference at index 4
                        if len(fields) > 4:
                            atm_ref_field = fields[4].strip()
                            clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                            if len(clean_ref) >= 4:
                                display_ref = clean_ref[:4]
                                group_ref = clean_ref[:4]

                    elif payment_mode == 'BDO':
                        # For BDO, amount is at index 9
                        if len(fields) > 9:
                            try:
                                amount_str = fields[9].strip()
                                amount = float(amount_str)
                                backend_total += amount
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error converting BDO amount: {fields[9]}, error: {str(e)}")
                                amount = 0

                        # For BDO, handle ATM reference at index 5
                        if len(fields) > 5:
                            atm_ref_field = fields[5].strip()
                            clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                            if len(clean_ref) >= 4:
                                display_ref = clean_ref[:4]
                                group_ref = clean_ref[:4]

                    elif payment_mode == 'ECPAY':
                        # For ECPAY, amount is in index 6
                        if len(fields) > 6:
                            try:
                                amount_str = fields[6].replace(',', '')
                                amount = float(amount_str)
                                backend_total += amount
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error converting ECPAY amount: {fields[6]}, error: {str(e)}")
                                amount = 0

                        # For ECPAY, handle ATM reference at index 5
                        if len(fields) > 5:
                            atm_ref_field = fields[5].strip()
                            clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                            if len(clean_ref) >= 4:
                                display_ref = clean_ref[:4]
                                group_ref = clean_ref[:4]

                    elif payment_mode == 'CHINABANK':
                        # For CHINABANK, amount is at index 2
                        if len(fields) > 2:
                            try:
                                amount_str = fields[2].replace(',', '')
                                amount = float(amount_str)
                                backend_total += amount
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error converting CHINABANK amount: {fields[2]}, error: {str(e)}")
                                amount = 0

                        # For CHINABANK, handle ATM reference at index 3
                        if len(fields) > 3:
                            atm_ref_field = fields[3].strip()
                            clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                            if len(clean_ref) >= 4:
                                display_ref = clean_ref[:4]
                                group_ref = clean_ref[:4]

                    elif payment_mode == 'CEBUANA':
                        # For CEBUANA, amount is at index 6
                        if len(fields) > 6:
                            try:
                                amount_str = fields[6].replace(',', '')
                                amount = float(amount_str)
                                backend_total += amount
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error converting CEBUANA amount: {fields[6]}, error: {str(e)}")
                                amount = 0

                        # For CEBUANA, handle ATM reference at index 4
                        if len(fields) > 4:
                            atm_ref_field = fields[4].strip()
                            clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                            if len(clean_ref) >= 4:
                                display_ref = clean_ref[:4]
                                group_ref = clean_ref[:4]

                    elif payment_mode == 'CIS':
                        # For CIS, amount is at index 2
                        if len(fields) > 2:
                            try:
                                amount_str = fields[2].replace(',', '')
                                amount = float(amount_str)
                                backend_total += amount
                            except (ValueError, TypeError) as e:
                                logger.error(f"Error converting CIS amount: {fields[2]}, error: {str(e)}")
                                amount = 0

                        # For CIS, handle ATM reference at index 1
                        if len(fields) > 1:
                            atm_ref_field = fields[1].strip()
                            clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                            if len(clean_ref) >= 4:
                                display_ref = clean_ref[:4]
                                group_ref = clean_ref[:4]

                    elif payment_mode == 'UNIONBANK':
                        # For UNIONBANK, find amount at the end of the line
                        try:
                            # Look for amount followed by either DB or LC (with or without additional digits)
                            amount_match = re.search(r'(\d{12})(?:DB|LC)\d*\s*$', line)
                            if amount_match:
                                amount_str = amount_match.group(1)  # Get the first 12 digits
                                amount = float(
                                    amount_str) / 100  # Convert to float and divide by 100 for decimal points
                                backend_total += amount
                            else:
                                amount = 0
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error converting UNIONBANK amount: {line}, error: {str(e)}")
                            amount = 0

                        # For UNIONBANK, handle ATM reference from the line
                        # First try to find a 14-digit reference
                        matches = re.finditer(r'\s{10,}(\d{14})\s+', line)
                        last_match = None
                        for match in matches:
                            last_match = match

                        if last_match:
                            atm_ref_field = last_match.group(1)  # This gets just the digits
                            clean_ref = atm_ref_field[:4]  # Take first 4 digits
                            display_ref = clean_ref
                            group_ref = clean_ref
                        else:
                            # If no 14-digit reference found, try to find any sequence of digits
                            # that could be an ATM reference (at least 4 digits)
                            ref_match = re.search(r'\s{10,}(\d{4,})\s+', line)
                            if ref_match:
                                atm_ref_field = ref_match.group(1)
                                clean_ref = atm_ref_field[:4]  # Take first 4 digits
                                display_ref = clean_ref
                                group_ref = clean_ref
                            else:
                                # If still no reference found, try to get it from index 4
                                fields = line.strip().split()
                                if len(fields) > 4:
                                    atm_ref_field = fields[4]
                                    clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())[:4]
                                    if len(clean_ref) >= 4:
                                        display_ref = clean_ref
                                        group_ref = clean_ref
                                    else:
                                        display_ref = '0000'
                                        group_ref = '0000'
                                else:
                                    display_ref = '0000'
                                    group_ref = '0000'

                    elif payment_mode == 'BANCNET':
                        # For BANCNET, handle ATM reference before the asterisk
                        asterisk_pos = line.find('*')
                        if asterisk_pos > 0:
                            atm_ref_field = line[asterisk_pos - 14:asterisk_pos - 10]
                            clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                            if len(clean_ref) >= 4:
                                display_ref = clean_ref[:4]
                                group_ref = clean_ref[:4]

                        # Extract amount after the asterisk using exact position approach
                        asterisk_pos = line.find('*')
                        if asterisk_pos > 0 and len(line) > asterisk_pos + 28:  # Need at least 28 characters after *
                            # Get the 8 digits after the first 20 characters following the asterisk
                            amount_str = line[asterisk_pos + 21:asterisk_pos + 29]
                            logger.debug(f'Amount string from positions after first 20 chars: {amount_str}')

                            try:
                                # Convert to float and divide by 100 to get the correct decimal place
                                amount = float(amount_str) / 100
                                if 0 < amount < 1000000:
                                    logger.debug(f'Found BANCNET amount {amount} from {amount_str}')
                                    grouped_data[atm_ref_field]['total_amount'] += amount
                                    total_bancnet_amount += amount  # Add to total BANCNET amount
                            except ValueError as e:
                                logger.error(f'Error converting BANCNET amount: {amount_str}, error: {str(e)}')

                        # Extract date from the first 20 characters
                        if len(line) >= 20:
                            first_20 = line[:20]
                            # Extract last 6 digits for date (YYMMDD format)
                            date_str = first_20[-6:]
                            try:
                                # Format as MM/DD/20YY
                                yy = date_str[:2]
                                mm = date_str[2:4]
                                dd = date_str[4:]
                                formatted_date = f"{mm}/{dd}/20{yy}"
                                if 'dates' not in grouped_data[atm_ref_field]:
                                    grouped_data[atm_ref_field]['dates'] = set()
                                grouped_data[atm_ref_field]['dates'].add(formatted_date)
                                logger.debug(f'Added BANCNET date {formatted_date} to ATM ref {atm_ref_field}')
                            except Exception as e:
                                logger.error(f'Error formatting BANCNET date: {date_str}, error: {str(e)}')

                        transaction = {
                            'payment_mode': payment_mode,
                            'amount': amount,
                            'raw_row': fields,
                            'original_line': line,
                            'display_ref': display_ref,
                            'group_ref': group_ref,
                            'dates': list(grouped_data[atm_ref_field].get('dates', set()))  # Include the dates
                        }

                        transactions.append(transaction)
                        total_transactions += 1

            # Group transactions based on display_ref if available, otherwise use atm_ref
            if transactions and 'display_ref' in transactions[0]:
                group_key = transactions[0]['display_ref']
            else:
                group_key = atm_ref

            processed_data[group_key] = transactions

        # Determine separator based on payment mode
        payment_modes = {data.get('payment_mode') for data in grouped_data.values() if isinstance(data, dict)}
        separator = '^' if 'PNB' in payment_modes else (
            '|' if 'BDO' in payment_modes else (
                ' ' if any(mode in ['METROBANK', 'CHINABANK'] for mode in payment_modes) else ','
            )
        )

        # Use the total_transactions we counted
        return jsonify({
            'status': 'completed',
            'progress': 100,
            'processed_data': processed_data,
            'raw_contents': raw_contents,
            'separator': separator,
            'summary': {
                'total_amount': backend_total,
                'total_transactions': total_transactions
            }
        })

    elif status['status'] == 'error':
        return jsonify({
            'status': 'error',
            'error': status.get('error', 'Unknown error occurred')
        }), 500
    else:
        return jsonify({
            'status': status['status']
        })


def process_file_content(content, filename):
    """Process file content and return structured data"""
    try:
        # Initialize results dictionary
        results = {}
        raw_contents = []
        total_transactions = 0

        # Detect payment mode from filename
        payment_mode = detect_payment_mode_from_filename(filename)
        logger.info(f"Detected payment mode from filename: {payment_mode}")

        # Split content into lines
        lines = content.strip().split('\n')
        logger.info(f"Processing {len(lines)} lines")

        # Group data by ATM reference
        grouped_data = {}

        # Process based on payment mode
        if payment_mode == 'CIS':
            # CIS specific processing
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                # For CIS, split by caret
                fields = [f.strip() for f in line.split('^')]

                # For CIS, ATM ref is in index 1
                if len(fields) > 1:
                    atm_ref_field = fields[1].strip()
                    # Clean the reference (keep only digits)
                    clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                    # Take first 4 digits as ATM ref
                    if len(clean_ref) >= 4:
                        atm_ref = clean_ref[:4]
                        logger.debug(f"Found CIS ATM ref: {atm_ref} from {atm_ref_field}")

                        if atm_ref not in grouped_data:
                            grouped_data[atm_ref] = {
                                'raw_contents': [],
                                'transaction_count': 0,
                                'total_amount': 0.0,
                                'payment_mode': payment_mode,
                                'dates': set()  # Initialize dates set
                            }
                        grouped_data[atm_ref]['raw_contents'].append(line)
                        grouped_data[atm_ref]['transaction_count'] += 1

                        # For CIS, amount is in index 2
                        try:
                            if len(fields) > 2:
                                amount_str = fields[2].replace(',', '')
                                amount = float(amount_str)
                                grouped_data[atm_ref]['total_amount'] += amount
                                logger.debug(f"Added CIS amount {amount} to ATM ref {atm_ref}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect CIS amount in line: {line}")

                        # For CIS, date is in index 0
                        try:
                            if len(fields) > 0:
                                date_str = fields[0].strip()
                                grouped_data[atm_ref]['dates'].add(date_str)
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect CIS date in line: {line}")

        elif payment_mode == 'METROBANK':
            # METROBANK specific processing
            total_metrobank_amount = 0.0  # Initialize total amount counter
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                # For METROBANK, split by spaces and get index 1
                fields = [f.strip() for f in line.split() if f.strip()]
                if len(fields) > 1:
                    atm_ref = fields[1].strip()
                    # Take only first 4 digits for grouping
                    atm_ref = atm_ref[:4]
                    logger.debug(f"Found METROBANK ATM ref: {atm_ref} from field: {fields[1]}")

                    if atm_ref not in grouped_data:
                        grouped_data[atm_ref] = {
                            'raw_contents': [],
                            'transaction_count': 0,
                            'total_amount': 0.0,
                            'payment_mode': payment_mode,
                            'dates': set()  # Initialize dates set
                        }
                    grouped_data[atm_ref]['raw_contents'].append(line)
                    grouped_data[atm_ref]['transaction_count'] += 1

                    # Extract amount from the line using regex
                    amount_match = re.search(r'(\d{11,12})[A-Z]', line)
                    if amount_match:
                        amount_str = amount_match.group(1)
                        amount = float(amount_str) / 100
                        grouped_data[atm_ref]['total_amount'] += amount
                        total_metrobank_amount += amount
                        logger.debug(f"Found METROBANK amount: {amount} from {amount_str}")

                    # Extract date from the line
                    date_match = re.search(r'(\d{6})\d*$', line)
                    if date_match:
                        date_str = date_match.group(1)
                        formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                        grouped_data[atm_ref]['dates'].add(f"{formatted_date}")
                        logger.debug(f"Found METROBANK date: {formatted_date} from {date_str}")

            # Store the total amount in the results
            results = {
                'grouped_data': grouped_data,
                'raw_contents': raw_contents,
                'payment_mode': payment_mode,
                'total_amount': total_metrobank_amount
            }
            logger.info(f"Total METROBANK amount: {total_metrobank_amount}")
            return results

        elif payment_mode == 'PNB':
            # PNB specific processing
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                # For PNB, split by caret
                fields = [f.strip() for f in line.split('^')]

                # For PNB, ATM ref is in field 5 (index 4)
                if len(fields) > 4:
                    atm_ref_field = fields[4].strip()
                    # Clean the reference (keep only digits)
                    clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                    # Take first 4 digits as ATM ref
                    if len(clean_ref) >= 4:
                        atm_ref = clean_ref[:4]
                        logger.debug(f"Found PNB ATM ref: {atm_ref} from {atm_ref_field}")

                        if atm_ref not in grouped_data:
                            grouped_data[atm_ref] = {
                                'raw_contents': [],
                                'transaction_count': 0,
                                'total_amount': 0.0,
                                'payment_mode': payment_mode,
                                'dates': set()  # Initialize dates set
                            }
                        grouped_data[atm_ref]['raw_contents'].append(line)
                        grouped_data[atm_ref]['transaction_count'] += 1

                        # For PNB, amount is in field 7 (index 6)
                        try:
                            if len(fields) > 6:
                                amount_str = fields[6].replace(',', '')
                                amount = float(amount_str)
                                grouped_data[atm_ref]['total_amount'] += amount
                                logger.debug(f"Added PNB amount {amount} to ATM ref {atm_ref}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect PNB amount in line: {line}")

                        # For PNB, date is in index 1
                        try:
                            if len(fields) > 1:
                                date_str = fields[1].strip()
                                grouped_data[atm_ref]['dates'].add(date_str)
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect PNB date in line: {line}")

        elif payment_mode == 'BDO':
            # BDO specific processing
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                fields = line.strip().split('|')

                atm_ref = detect_atm_reference_by_payment_mode(fields, payment_mode, line)
                if atm_ref:
                    if atm_ref not in grouped_data:
                        grouped_data[atm_ref] = {
                            'raw_contents': [],
                            'transaction_count': 0,
                            'total_amount': 0.0,
                            'payment_mode': payment_mode,
                            'dates': set()  # Initialize dates set
                        }
                    grouped_data[atm_ref]['raw_contents'].append(line)
                    grouped_data[atm_ref]['transaction_count'] += 1

                    # For BDO, amount is in index 9
                    try:
                        if len(fields) > 9:
                            amount_str = fields[9].strip()
                            amount = float(amount_str)
                            grouped_data[atm_ref]['total_amount'] += amount
                            logger.debug(f"Added BDO amount {amount} to ATM ref {atm_ref}")
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Could not detect BDO amount in line: {line}")

                    # Extract date from index 2
                    try:
                        if len(fields) > 2:
                            date_str = fields[2].strip()
                            grouped_data[atm_ref]['dates'].add(date_str)
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Could not detect BDO date in line: {line}")

        elif payment_mode == 'ECPAY':
            # ECPAY specific processing
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                # For ECPAY, split by comma
                fields = [f.strip() for f in line.split(',')]

                atm_ref = detect_atm_reference_by_payment_mode(fields, payment_mode, line)
                if atm_ref:
                    if atm_ref not in grouped_data:
                        grouped_data[atm_ref] = {
                            'raw_contents': [],
                            'transaction_count': 0,
                            'total_amount': 0.0,
                            'payment_mode': payment_mode,
                            'dates': set()  # Initialize dates set
                        }
                    grouped_data[atm_ref]['raw_contents'].append(line)
                    grouped_data[atm_ref]['transaction_count'] += 1

                    # For ECPAY, amount is in index 6
                    try:
                        if len(fields) > 6:
                            amount_str = fields[6].replace(',', '')
                            amount = float(amount_str)
                            grouped_data[atm_ref]['total_amount'] += amount
                            logger.debug(f"Added ECPAY amount {amount} to ATM ref {atm_ref}")
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Could not detect ECPAY amount in line: {line}")

                    # For ECPAY, date is in index 2
                    try:
                        if len(fields) > 2:
                            date_str = fields[2].strip()
                            if date_str:
                                grouped_data[atm_ref]['dates'].add(f"{date_str}")
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Could not detect ECPAY date in line: {line}")

        elif payment_mode == 'CHINABANK':
            # CHINABANK specific processing
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                # Split by multiple spaces for CHINABANK's fixed-width format
                fields = [f for f in re.split(r'\s+', line.strip()) if f.strip()]

                # For CHINABANK, ATM ref is in index 3
                if len(fields) > 3:
                    atm_ref_field = fields[3].strip()
                    # Clean the reference (keep only digits)
                    clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                    # Take first 4 digits as ATM ref
                    if len(clean_ref) >= 4:
                        atm_ref = clean_ref[:4]
                        logger.debug(f"Found CHINABANK ATM ref: {atm_ref} from {atm_ref_field}")

                        if atm_ref not in grouped_data:
                            grouped_data[atm_ref] = {
                                'raw_contents': [],
                                'transaction_count': 0,
                                'total_amount': 0.0,
                                'payment_mode': payment_mode,
                                'dates': set()  # Initialize dates set
                            }
                        grouped_data[atm_ref]['raw_contents'].append(line)
                        grouped_data[atm_ref]['transaction_count'] += 1

                        # For CHINABANK, amount is in index 2
                        try:
                            if len(fields) > 2:
                                amount_str = fields[2].replace(',', '')
                                amount = float(amount_str)
                                grouped_data[atm_ref]['total_amount'] += amount
                                logger.debug(f"Added CHINABANK amount {amount} to ATM ref {atm_ref}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect CHINABANK amount in line: {line}")

                        # For CHINABANK, date is in index 0
                        try:
                            if len(fields) > 0:
                                date_str = fields[0].strip()
                                if date_str:
                                    # Format the date from MMDDYYYY to MM/DD/YYYY
                                    formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                    grouped_data[atm_ref]['dates'].add(f"{formatted_date}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect CHINABANK date in line: {line}")

        elif payment_mode == 'CEBUANA':
            # CEBUANA specific processing
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                # For CEBUANA, split by comma
                fields = [f.strip() for f in line.split(',')]

                # For CEBUANA, ATM ref is in index 4
                if len(fields) > 4:
                    atm_ref_field = fields[4].strip()
                    # Clean the reference (keep only digits)
                    clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())
                    # Take first 4 digits as ATM ref
                    if len(clean_ref) >= 4:
                        atm_ref = clean_ref[:4]
                        logger.debug(f"Found CEBUANA ATM ref: {atm_ref} from {atm_ref_field}")

                        if atm_ref not in grouped_data:
                            grouped_data[atm_ref] = {
                                'raw_contents': [],
                                'transaction_count': 0,
                                'total_amount': 0.0,
                                'payment_mode': payment_mode,
                                'dates': set()  # Initialize dates set
                            }
                        grouped_data[atm_ref]['raw_contents'].append(line)
                        grouped_data[atm_ref]['transaction_count'] += 1

                        # For CEBUANA, amount is in index 6 (last field)
                        try:
                            if len(fields) > 6:
                                amount_str = fields[6].replace(',', '')
                                amount = float(amount_str)
                                grouped_data[atm_ref]['total_amount'] += amount
                                logger.debug(f"Added CEBUANA amount {amount} to ATM ref {atm_ref}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect CEBUANA amount in line: {line}")

                        # For CEBUANA, dates are in index 1 and 2
                        try:
                            if len(fields) > 2:
                                date = fields[2].strip()
                                if date:
                                    grouped_data[atm_ref]['dates'] = {date}  # Only add date
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect CEBUANA date in line: {line}")

        elif payment_mode == 'UNIONBANK':
            # UNIONBANK specific processing
            current_atm_ref = None  # Track current ATM reference

            for line in lines:
                if not line.strip():
                    continue

                # For UNIONBANK, we want to keep all lines
                # First, try to find a line with an ATM reference
                if len(line) >= 200:  # Check if line is long enough to contain ATM ref
                    # Look for the ATM reference pattern in the line
                    matches = re.finditer(r'\s{10,}(\d{14})\s+', line)
                    last_match = None
                    for match in matches:
                        last_match = match

                    if last_match:
                        atm_ref_field = last_match.group(1)  # This gets just the digits
                        current_atm_ref = atm_ref_field[:4]  # Take first 4 digits
                    else:
                        # If no 14-digit reference found, try to find any sequence of digits
                        # that could be an ATM reference (at least 4 digits)
                        ref_match = re.search(r'\s{10,}(\d{4,})\s+', line)
                        if ref_match:
                            atm_ref_field = ref_match.group(1)
                            current_atm_ref = atm_ref_field[:4]  # Take first 4 digits
                        else:
                            # If still no reference found, try to get it from index 4
                            fields = line.strip().split()
                            if len(fields) > 4:
                                atm_ref_field = fields[4]
                                clean_ref = ''.join(c for c in atm_ref_field if c.isdigit())[:4]
                                if len(clean_ref) >= 4:
                                    current_atm_ref = clean_ref
                                else:
                                    current_atm_ref = '0000'
                            else:
                                current_atm_ref = '0000'

                    if current_atm_ref not in grouped_data:
                        grouped_data[current_atm_ref] = {
                            'raw_contents': [],
                            'transaction_count': 0,
                            'total_amount': 0.0,
                            'payment_mode': payment_mode,
                            'dates': set()
                        }

                    # Add the line to the current ATM reference group
                    if line not in grouped_data[current_atm_ref]['raw_contents']:
                        try:
                            # Find the amount at the end of the line (12 digits followed by 'DB')
                            amount_match = re.search(r'(\d{12})(?:DB|LC)\d*\s*$', line)
                            if amount_match:
                                amount_str = amount_match.group(1)  # Get the first 12 digits
                                amount = float(
                                    amount_str) / 100  # Convert to float and divide by 100 for decimal points
                                grouped_data[current_atm_ref]['total_amount'] += amount
                                logger.debug(f"Added UNIONBANK amount {amount} to ATM ref {current_atm_ref}")
                            else:
                                amount = 0.0

                            # Extract date that appears after UB followed by digits
                            date_match = re.search(r'UB\d+\s+(\d{6})', line)
                            if date_match:
                                date_str = date_match.group(1)
                                formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                                grouped_data[current_atm_ref]['dates'].add(f"{formatted_date}")
                                logger.debug(f"Added UNIONBANK date {formatted_date} to ATM ref {current_atm_ref}")

                            # Add the line to raw_contents
                            grouped_data[current_atm_ref]['raw_contents'].append(line)
                            grouped_data[current_atm_ref]['transaction_count'] += 1
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Could not detect UNIONBANK amount in line: {line}")
                            # Still add the line even if amount detection fails
                            grouped_data[current_atm_ref]['raw_contents'].append(line)
                            grouped_data[current_atm_ref]['transaction_count'] += 1

                # If we have a current ATM reference but this line doesn't contain one,
                # it's probably related to the current transaction
                elif current_atm_ref and current_atm_ref in grouped_data:
                    # Add the line to the current ATM reference group
                    if line not in grouped_data[current_atm_ref]['raw_contents']:
                        grouped_data[current_atm_ref]['raw_contents'].append(line)

                # If we don't have a current ATM reference, create a default group
                else:
                    if 'NOREF' not in grouped_data:
                        grouped_data['NOREF'] = {
                            'raw_contents': [],
                            'transaction_count': 0,
                            'total_amount': 0.0,
                            'payment_mode': payment_mode,
                            'dates': set()
                        }
                    if line not in grouped_data['NOREF']['raw_contents']:
                        grouped_data['NOREF']['raw_contents'].append(line)

        elif payment_mode == 'SM':
            # SM specific processing
            logger.debug("Starting SM file processing")
            total_sm_amount = 0.0  # Initialize total amount counter
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                logger.debug(f"Processing SM line: {line}")

                # For SM, extract ATM reference from position 18:31 (0-based)
                if len(line) >= 45:  # Ensure line is long enough
                    atm_ref = line[18:31]  # Extract ATM reference
                    first_four = atm_ref[:4]  # Get first 4 digits for grouping
                    logger.debug(f"Extracted ATM ref: {atm_ref}, First four: {first_four}")

                    if first_four not in grouped_data:
                        logger.debug(f"Creating new group for first four: {first_four}")
                        grouped_data[first_four] = {
                            'raw_contents': [],
                            'transaction_count': 0,
                            'total_amount': 0.0,
                            'payment_mode': payment_mode,
                            'dates': set(),
                            'atm_refs': set()  # Store all ATM refs for this group
                        }

                    # Add the ATM ref to the set of refs for this group
                    grouped_data[first_four]['atm_refs'].add(atm_ref)

                    # Add the line to raw_contents
                    grouped_data[first_four]['raw_contents'].append(line)
                    grouped_data[first_four]['transaction_count'] += 1

                    # Extract amount (digits before 'CS')
                    cs_pos = line.find('CS')
                    if cs_pos > 0:
                        # Look backwards from CS to find the amount
                        # The amount is typically 5-7 digits before CS
                        amount_str = ''
                        for i in range(cs_pos - 1, max(0, cs_pos - 10), -1):
                            if line[i].isdigit():
                                amount_str = line[i] + amount_str
                            else:
                                break

                        if amount_str:
                            amount = float(amount_str) / 100  # Convert to float and divide by 100
                            total_sm_amount += amount  # Add to total SM amount
                            grouped_data[first_four]['total_amount'] += amount
                            logger.debug(f"Found SM amount: {amount} from {amount_str}")
                    else:
                        logger.debug(f"No 'CS' found in line: {line}")

                    # Extract date (from position 3-11 for MMDDYYYY format)
                    if len(line) >= 11:  # Ensure line is long enough
                        date_str = line[3:11]  # Extract date from positions 3-11
                        if date_str:
                            # Format the date from MMDDYYYY to MM/DD/YYYY
                            formatted_date = f"{date_str[:2]}/{date_str[2:4]}/{date_str[4:]}"
                            grouped_data[first_four]['dates'].add(f"{formatted_date}")
                            logger.debug(f"Added date {formatted_date} to ATM ref {first_four}")
                else:
                    logger.debug(f"Line too short for SM processing: {line}")

            # Store the total amount in the results
            results = {
                'grouped_data': grouped_data,
                'raw_contents': raw_contents,
                'payment_mode': payment_mode,
                'total_amount': total_sm_amount
            }
            logger.info(f"Total SM amount: {total_sm_amount}")
            return results

        elif payment_mode == 'BANCNET':
            # BANCNET specific processing
            total_bancnet_amount = 0.0  # Initialize total amount counter
            for line in lines:
                if not line.strip():
                    continue

                raw_contents.append(line)
                # Detect ATM reference before the asterisk
                asterisk_pos = line.find('*')
                if asterisk_pos > 0:
                    atm_ref_field = line[asterisk_pos - 14:asterisk_pos - 10]
                    if atm_ref_field not in grouped_data:
                        grouped_data[atm_ref_field] = {
                            'raw_contents': [],
                            'transaction_count': 0,
                            'total_amount': 0.0,
                            'payment_mode': payment_mode,
                            'dates': set()  # Initialize dates set
                        }
                    grouped_data[atm_ref_field]['raw_contents'].append(line)
                    grouped_data[atm_ref_field]['transaction_count'] += 1

                    # Extract amount from the line
                    # Find the last asterisk position
                    last_asterisk_pos = line.rfind('*')
                    if last_asterisk_pos > 0 and len(line) > last_asterisk_pos + 28:
                        # Get the 8 digits after the first 20 characters following the asterisk
                        amount_str = line[last_asterisk_pos + 21:last_asterisk_pos + 29]
                        logger.debug(f'BANCNET - Amount string from positions after first 20 chars: {amount_str}')

                        try:
                            # Convert to float and divide by 100 to get the correct decimal place
                            amount = float(amount_str) / 100
                            if 0 < amount < 1000000:
                                logger.debug(f'Found BANCNET amount {amount} from {amount_str}')
                                grouped_data[atm_ref_field]['total_amount'] += amount
                                total_bancnet_amount += amount  # Add to total BANCNET amount
                        except ValueError as e:
                            logger.error(f'Error converting BANCNET amount: {amount_str}, error: {str(e)}')

                    # Extract date from the first 20 characters
                    if len(line) >= 20:
                        first_20 = line[:20]
                        # Extract last 6 digits for date (YYMMDD format)
                        date_str = first_20[-6:]
                        # Format as MM/DD/20YY
                        try:
                            yy = date_str[:2]
                            mm = date_str[2:4]
                            dd = date_str[4:]
                            formatted_date = f"{mm}/{dd}/20{yy}"
                            grouped_data[atm_ref_field]['dates'].add(formatted_date)
                            logger.debug(f'Added BANCNET date {formatted_date} to ATM ref {atm_ref_field}')
                        except Exception as e:
                            logger.error(f'Error formatting BANCNET date: {date_str}, error: {str(e)}')

            # Store the total amount in the results
            results = {
                'grouped_data': grouped_data,
                'raw_contents': raw_contents,
                'payment_mode': payment_mode,
                'total_amount': total_bancnet_amount
            }
            logger.info(f"Total BANCNET amount: {total_bancnet_amount}")
            return results

        # Log processing results
        for atm_ref, data in grouped_data.items():
            logger.info(
                f"ATM {atm_ref}: {data['transaction_count']} transactions, total amount: {data['total_amount']}")

        # Convert dates set to sorted list for each ATM ref
        for atm_ref in grouped_data:
            if 'dates' in grouped_data[atm_ref]:
                grouped_data[atm_ref]['dates'] = [f'{date}' for date in
                                                  sorted(list(grouped_data[atm_ref]['dates']))]

        return {
            'grouped_data': grouped_data,
            'raw_contents': raw_contents,
            'payment_mode': payment_mode
        }

    except Exception as e:
        logger.error(f"Error processing file content: {str(e)}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise


if __name__ == '__main__':
    # Get your computer's IP address
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"\nAccess the application from other computers using:")
    print(f"http://{local_ip}:5000")
    print(f"\nMake sure your firewall allows connections on port 5000")
    print(f"Project root: {project_root}")
    print(f"Static folder path: {static_folder}")
    print(f"Static folder exists: {os.path.exists(static_folder)}")
    print(f"Index.html exists: {os.path.exists(os.path.join(static_folder, 'index.html'))}")

    # Create a custom server with increased timeout and thread support
    server = make_server('0.0.0.0', 5000, app)
    server.timeout = 1800  # 30 minutes timeout

    # Set server options to handle large files
    server.max_request_body_size = 1024 * 1024 * 1024  # 1GB
    server.max_request_header_size = 1024 * 1024  # 1MB

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
        sys.exit(0)
