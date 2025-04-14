import React, { useState, useMemo } from 'react';
import './DataTable.css';

const DataTable = ({ data, onDownload, onDownloadAll }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 50;

  // Function to detect if a value is an amount
  const isAmount = (value) => {
    if (!value) return false;
    
    // Clean the value - remove currency symbols, commas and spaces
    const cleanValue = value.toString().trim().replace(/[₱,\s]/g, '');
    
    // Debug log
    console.log('Checking if amount:', value, 'Clean value:', cleanValue);
    
    // Only detect numbers with decimal points (0.0 to 0.0000 format)
    const isAmountValue = /^\d+\.\d+$/.test(cleanValue);
    console.log('Is amount?', isAmountValue);
    return isAmountValue;
  };

  // Format amount as PHP currency
  const formatAmount = (amount) => {
    try {
      if (!amount) return '₱0.00';
      
      // Clean the value - remove currency symbols, commas and spaces
      const cleanAmount = amount.toString().trim().replace(/[₱,\s]/g, '');
      const numAmount = parseFloat(cleanAmount);
      
      console.log('Formatting amount:', amount, 'Clean amount:', cleanAmount, 'Parsed:', numAmount);
      
      if (isNaN(numAmount)) return '₱0.00';

      // Get the decimal places from the original number
      const decimalPlaces = cleanAmount.includes('.') ? 
        cleanAmount.split('.')[1].length : 0;

      console.log('Decimal places:', decimalPlaces);

      // Format based on decimal places in the original number
      if (decimalPlaces === 1) {
        // For .0 to .9, show 1 decimal place
        return '₱' + numAmount.toLocaleString('en-PH', {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1
        });
      } else if (decimalPlaces === 2) {
        // For .00 to .99, show 2 decimal places
        return new Intl.NumberFormat('en-PH', {
          style: 'currency',
          currency: 'PHP',
          minimumFractionDigits: 2,
          maximumFractionDigits: 2
        }).format(numAmount);
      } else {
        // For 3 or more decimal places (.000+), show all decimal places
        return '₱' + numAmount.toLocaleString('en-PH', {
          minimumFractionDigits: decimalPlaces,
          maximumFractionDigits: decimalPlaces
        });
      }
    } catch (e) {
      console.error('Error formatting amount:', e);
      return '₱0.00';
    }
  };

  // Calculate summary information
  const summary = useMemo(() => {
    if (!data) return null;
    if (!Array.isArray(data)) {
      console.error('Data is not an array:', data);
      return null;
    }

    let totalAmount = 0;
    let amountCount = 0;

    data.forEach(row => {
      if (row.amount) {
        const cleanValue = row.amount.toString().trim().replace(/[₱,\s]/g, '');
        console.log('Processing row amount:', row.amount, 'Clean value:', cleanValue);
        const amount = parseFloat(cleanValue);
        if (!isNaN(amount)) {
          totalAmount += amount;
          amountCount++;
        }
      }
    });

    console.log('Summary calculation:', { totalRows: data.length, amountCount, totalAmount });
    return {
      totalRows: data.length,
      amountCount,
      totalAmount
    };
  }, [data]);

  const filteredData = useMemo(() => {
    if (!data) {
      console.error('Data is null or undefined');
      return [];
    }

    if (!Array.isArray(data)) {
      console.error('Data is not an array:', data);
      return [];
    }

    console.log('DataTable received data:', data);
    let filtered = data;

    // Filter by search term
    if (searchTerm) {
      filtered = data.filter(row => {
        return Object.values(row).some(value => 
          value && value.toString().toLowerCase().includes(searchTerm.toLowerCase())
        );
      });
    }

    return filtered;
  }, [data, searchTerm]);

  // Calculate pagination
  const totalPages = Math.ceil(filteredData.length / rowsPerPage);
  const startIndex = (currentPage - 1) * rowsPerPage;
  const endIndex = startIndex + rowsPerPage;
  const currentData = filteredData.slice(startIndex, endIndex);

  const handlePageChange = (page) => {
    setCurrentPage(page);
  };

  const renderSummary = () => {
    if (!data || !data.summary) return null;

    const { total_amount, total_transactions } = data.summary;
    const groupedData = data.processed_data || {};

    return (
      <div className="summary-container">
        <div className="summary-header">
          <h3>Summary</h3>
          <div className="summary-actions">
            <button onClick={onDownloadAll} className="download-all-btn">
              Download All Files
            </button>
          </div>
        </div>
        <div className="summary-content">
          <div className="summary-item">
            <span className="summary-label">Total Amount:</span>
            <span className="summary-value">₱{total_amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </div>
          <div className="summary-item">
            <span className="summary-label">Total Transactions:</span>
            <span className="summary-value">{total_transactions}</span>
          </div>
          <div className="summary-item">
            <span className="summary-label">Total ATM References:</span>
            <span className="summary-value">{Object.keys(groupedData).length}</span>
          </div>
        </div>
        <div className="atm-summary">
          <h4>ATM Reference Summary</h4>
          <div className="atm-summary-grid">
            {Object.entries(groupedData).map(([atmRef, groupData]) => (
              <div key={atmRef} className="atm-summary-item">
                <div className="atm-ref-header">
                  <span className="atm-ref">ATM Reference: {atmRef}</span>
                  <button onClick={() => onDownload(atmRef)} className="download-btn">
                    Download
                  </button>
                </div>
                <div className="atm-details">
                  <div className="atm-detail-item">
                    <span className="detail-label">Transactions:</span>
                    <span className="detail-value">{groupData.length}</span>
                  </div>
                  <div className="atm-detail-item">
                    <span className="detail-label">Total Amount:</span>
                    <span className="detail-value">₱{groupData.reduce((sum, t) => sum + (t.amount || 0), 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  if (!data) {
    return <div className="data-table-container">No data available</div>;
  }

  if (!Array.isArray(data)) {
    console.error('Invalid data format:', data);
    return <div className="data-table-container">Invalid data format</div>;
  }

  if (data.length === 0) {
    return <div className="data-table-container">No data available</div>;
  }

  // Get all unique keys from the data
  const columns = useMemo(() => {
    const keys = new Set();
    data.forEach(row => {
      Object.keys(row).forEach(key => {
        // Exclude raw_lines and line_number from display
        if (key !== 'raw_lines' && key !== 'line_number') {
          keys.add(key);
        }
      });
    });
    return Array.from(keys);
  }, [data]);

  return (
    <div className="data-table-container">
      {renderSummary()}

      <div className="table-controls">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search in contents..."
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
              setCurrentPage(1); // Reset to first page when searching
            }}
          />
        </div>
        <div className="table-info">
          <div>Showing {currentData.length} of {filteredData.length} entries</div>
        </div>
      </div>

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map(column => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {currentData.map((row, rowIndex) => (
              <tr key={startIndex + rowIndex}>
                {columns.map(column => {
                  const value = row[column];
                  // Skip rendering raw_lines column
                  if (column === 'raw_lines') return null;
                  
                  // Determine cell type based on content
                  let className = 'text';
                  if (column === 'amount' || isAmount(value)) {
                    className = 'amount';
                    console.log('Found amount in column:', column, 'value:', value);
                  } else if (/^\d+$/.test(value)) {
                    className = 'code';
                  } else if (value && value.length > 30) {
                    className = 'long-text';
                  }
                  
                  return (
                    <td key={column} className={className}>
                      {(column === 'amount' || isAmount(value)) ? formatAmount(value) : value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <button
            onClick={() => handlePageChange(1)}
            disabled={currentPage === 1}
          >
            First
          </button>
          <button
            onClick={() => handlePageChange(currentPage - 1)}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span>
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => handlePageChange(currentPage + 1)}
            disabled={currentPage === totalPages}
          >
            Next
          </button>
          <button
            onClick={() => handlePageChange(totalPages)}
            disabled={currentPage === totalPages}
          >
            Last
          </button>
        </div>
      )}
    </div>
  );
};

export default DataTable; 