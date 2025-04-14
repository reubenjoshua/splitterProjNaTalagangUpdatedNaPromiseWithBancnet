import React, { useState, useRef, useMemo, useCallback, useEffect } from 'react';
import FileUpload from './components/FileUpload';
import DataTable from './components/DataTable';
import JSZip from 'jszip';
import axios from 'axios';
import './App.css';

// API URL configuration
const API_URL = import.meta.env.VITE_API_URL || 'http://10.15.66.119:5000';

// Custom debounce function
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);

  return debouncedValue;
}

function App() {
  const [file, setFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [processingProgress, setProcessingProgress] = useState(0);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [reportProgress, setReportProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('idle');
  const [processingId, setProcessingId] = useState(null);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [processedData, setProcessedData] = useState(null);
  const [rawContents, setRawContents] = useState(null);
  const [separator, setSeparator] = useState(null);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [selectedPaymentMode, setSelectedPaymentMode] = useState("");
  const [selectedArea, setSelectedArea] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStatus, setProcessingStatus] = useState(null);
  const [summary, setSummary] = useState({ total_amount: 0, total_transactions: 0 });
  const [dates, setDates] = useState([]);
  const fileInputRef = useRef(null);

  const debouncedSearchTerm = useDebounce(searchTerm, 300);

  const filteredContents = useMemo(() => {
    if (!rawContents) return [];
    if (!debouncedSearchTerm) return rawContents;
    
    return rawContents.filter(content => 
      String(content).toLowerCase().includes(debouncedSearchTerm.toLowerCase())
    );
  }, [rawContents, debouncedSearchTerm]);

  const handleSearchChange = (e) => {
    setIsSearching(true);
    setSearchTerm(e.target.value);
  };

  const clearSearch = () => {
    setSearchTerm("");
    setIsSearching(false);
  };

  useEffect(() => {
    setIsSearching(false);
  }, [debouncedSearchTerm]);

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      handleFileChange({ target: { files: [droppedFile] } });
    }
  };

  const handleFileChange = async (event) => {
    const selectedFile = event.target.files[0];
    if (!selectedFile) return;

    if (!selectedPaymentMode) {
      setError('Please select a payment mode first');
      return;
    }

    if (!selectedArea) {
      setError('Please select an area first');
      return;
    }

    setFile(selectedFile);
    setUploadedFile(selectedFile);
    setUploadStatus('uploading');
    setError(null);
    setProcessedData(null);
    setRawContents(null);

    try {
      console.log('Starting file upload...');
      console.log('File name:', selectedFile.name);
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('payment_mode', selectedPaymentMode);
      formData.append('area', selectedArea);

      const response = await axios.post(`${API_URL}/api/upload-file`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      console.log('Upload response:', response.data);
      if (!response.data || !response.data.processing_id) {
        throw new Error('Invalid response from server: missing processing_id');
      }

      const { processing_id } = response.data;
      setProcessingId(processing_id);
      setUploadStatus('processing');
      pollProcessingStatus(processing_id);
    } catch (error) {
      console.error('Upload error:', error);
      console.error('Error details:', {
        message: error.message,
        response: error.response?.data,
        status: error.response?.status
      });
      setError(error.response?.data?.error || error.message || 'Failed to upload file');
      setUploadStatus('error');
    }
  };

  const pollProcessingStatus = async (processingId) => {
    try {
        const response = await fetch(`${API_URL}/api/processing-status/${processingId}`);
        if (!response.ok) {
            throw new Error('Failed to get processing status');
        }

        const data = await response.json();
        
        if (data.status === 'completed') {
            const processedDataWithSummary = {
                ...data.processed_data,
                summary: data.summary
            };
            
            setProcessedData(processedDataWithSummary);
            setRawContents(data.raw_contents);
            setSeparator(data.separator || '');
            setDates(extractDates(data.raw_contents));
            setIsProcessing(false);
            setUploadStatus('completed');
        } else if (data.status === 'error') {
            setError(data.error || 'Error processing file');
            setIsProcessing(false);
            setUploadStatus('error');
        } else {
            // Still processing, continue polling
            setTimeout(() => pollProcessingStatus(processingId), 1000);
        }
    } catch (error) {
        setError(error.message);
        setIsProcessing(false);
        setUploadStatus('error');
    }
  };

  const handleGenerateReport = async () => {
    if (!processedData || !rawContents) {
        setError('No data available for report generation');
        return;
    }

    setGeneratingReport(true);
    setError(null);

    try {
        // Get the original file name without extension
        const originalFileName = uploadedFile?.name || 'report';
        const baseFileName = originalFileName.split('.').slice(0, -1).join('.');

        const requestData = {
            processed_data: processedData,
            raw_contents: rawContents,
            separator: separator,
            original_filename: baseFileName,
            area: selectedArea
        };

        const response = await fetch(`${API_URL}/api/generate-report`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestData)
        });

        if (!response.ok) {
            throw new Error('Failed to generate report');
        }

        // Get the blob from the response
        const blob = await response.blob();
        
        // Create a download link for the ZIP file
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        
        // Get the filename from the response headers
        const contentDisposition = response.headers.get('content-disposition');
        let filename;
        
        if (contentDisposition) {
            // Extract filename from content-disposition header
            const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(contentDisposition);
            if (matches != null && matches[1]) {
                filename = matches[1].replace(/['"]/g, '');
            }
        }
        
        // If no filename from headers, use a default one
        if (!filename) {
            filename = `${baseFileName}_${selectedArea}.zip`;
        }
        
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);

        setGeneratingReport(false);
        setReportProgress(0);
        setError(null);
    } catch (error) {
        console.error('Error generating report:', error);
        setError(error.message || 'Failed to generate report');
        setGeneratingReport(false);
        setReportProgress(0);
    }
  };

  // Add function to clean the line content
  const cleanLineContent = (line) => {
    if (!line) return '';
    
    // Remove common separators
    const cleanedLine = line
      .replace(/\|/g, ' ')  // Remove vertical bars
      .replace(/\^/g, ' ')  // Remove carets
      .replace(/,/g, ' ')   // Remove commas
      .replace(/\s+/g, ' ') // Replace multiple spaces with single space
      .trim();              // Remove leading/trailing spaces
    
    return cleanedLine;
  };

  // Add function to calculate total amount
  const calculateTotalAmount = (contents) => {
    if (!contents || !Array.isArray(contents)) return 0;
    
    let total = 0;
    contents.forEach(line => {
      // Only match numbers that have decimal points
      const amountRegex = /\b\d+\.\d{1,4}\b/g;
      const matches = line.match(amountRegex);
      
      if (matches) {
        matches.forEach(match => {
          const amount = parseFloat(match);
          if (!isNaN(amount) && amount > 0 && amount < 1000000) {
            const roundedAmount = Math.round(amount * 100) / 100;
            total += roundedAmount;
          }
        });
      }
    });
    
    return Math.round(total * 100) / 100;
  };

  const extractDates = (contents) => {
    if (!contents) return [];
    
    const dateSet = new Set();
    contents.forEach(content => {
      // Match dates in the format MM/DD/YYYY
      const dateMatch1 = content.match(/\b\d{1,2}\/\d{1,2}\/\d{4}\b/);
      if (dateMatch1) {
        dateSet.add(dateMatch1[0]);
      }
      
      // Match dates in the format YYYYMMDD
      const dateMatch2 = content.match(/\b\d{4}\d{2}\d{2}\b/);
      if (dateMatch2) {
        // Convert YYYYMMDD to MM/DD/YYYY
        const formattedDate = `${dateMatch2[0].slice(4, 6)}/${dateMatch2[0].slice(6, 8)}/${dateMatch2[0].slice(0, 4)}`;
        dateSet.add(formattedDate);
      }
    });
    
    console.log('Extracted Dates:', Array.from(dateSet));
    return Array.from(dateSet);
  };

  const paymentModes = ['BDO', 'CEBUANA', 'CHINABANK', 'ECPAY', 'METROBANK', 'UNIONBANK', 'SM', 'PNB', 'CIS', 'BANCNET'];
  const areas = ['EPR', 'PIC', 'FPR'];

  return (
    <div className="app-container">
      <div className="header">
        <h1>Splitter</h1>
        <p className="subtitle">Upload your transaction file to process ATM references</p>
      </div>

      <div className="payment-mode-selector">
        <label htmlFor="payment-mode">Select Payment Mode:</label>
        <select
          id="payment-mode"
          value={selectedPaymentMode}
          onChange={(e) => setSelectedPaymentMode(e.target.value)}
          className="payment-mode-dropdown"
        >
          <option value="">Select a payment mode</option>
          {paymentModes.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </div>

      <div className="area-selector">
        <label htmlFor="area">Select Area:</label>
        <select
          id="area"
          value={selectedArea}
          onChange={(e) => setSelectedArea(e.target.value)}
          className="area-dropdown"
        >
          <option value="">Select Area</option>
          {areas.map((area) => (
            <option key={area} value={area}>
              {area}
            </option>
          ))}
        </select>
      </div>

      <div className="upload-section">
        <div className="upload-box" onDragOver={handleDragOver} onDrop={handleDrop}>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".txt,.csv"
            style={{ display: 'none' }}
          />
          <div className="upload-content">
            <div className="upload-icon">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <p>Drag and drop your file here</p>
            <p>or</p>
            <button className="browse-button" onClick={() => fileInputRef.current?.click()}>
              Browse Files
            </button>
            <p className="file-types">Supported formats: .txt</p>
          </div>
        </div>
      </div>

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      {uploadStatus === 'processing' && (
        <div className="processing-status">
          <div className="spinner"></div>
          <p>Processing file... {processingProgress}%</p>
        </div>
      )}

      {generatingReport && (
        <div className="processing-status">
          <div className="spinner"></div>
          <p>Generating report... {reportProgress}%</p>
        </div>
      )}

      {rawContents && rawContents.length > 0 && (
        <div className="results-section">
          <div className="results-header">
            <h2>File Contents</h2>
            <div className="results-actions">
              <button 
                className="generate-button"
                onClick={handleGenerateReport}
                disabled={generatingReport || !processedData}
              >
                Generate Report
              </button>
            </div>
          </div>

          <div className="search-section">
            <div className="search-container">
              <div className="search-input-wrapper">
                <span className="search-icon">🔍</span>
                <input
                  type="text"
                  className="search-input"
                  placeholder="Search contents..."
                  value={searchTerm}
                  onChange={handleSearchChange}
                />
                {searchTerm && (
                  <button className="clear-search" onClick={clearSearch}>
                    ✕
                  </button>
                )}
              </div>
              <div className="search-status">
                {isSearching ? (
                  "Searching..."
                ) : (
                  `Found ${filteredContents.length} entries${
                    searchTerm ? ` for "${searchTerm}"` : ""
                  }`
                )}
              </div>
            </div>
          </div>

          <div className="summary-section">
            <div className="summary-item">
              <span className="summary-label">Total Rows:</span>
              <span className="summary-value">{filteredContents.length}</span>
            </div>
            {console.log('Render - Full processedData:', processedData)}
            {console.log('Render - Summary:', processedData?.summary)}
            {console.log('Render - Total amount:', processedData?.summary?.total_amount)}
            <div className="summary-item">
              <span className="summary-label">Total Amount:</span>
              <span className="summary-value">₱{Number(processedData?.summary?.total_amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            </div>
            {dates.length > 0 && (
              <div className="summary-item">
                <span className="summary-label">Dates:</span>
                <span className="summary-value">
                  {dates.map(date => {
                    // Format date to MM/DD/YYYY if needed
                    if (date.includes('/')) {
                      return date; // Already in MM/DD/YYYY
                    } else {
                      // Convert YYYYMMDD to MM/DD/YYYY
                      return `${date.slice(4, 6)}/${date.slice(6, 8)}/${date.slice(0, 4)}`;
                    }
                  }).join(', ')}
                </span>
              </div>
            )}
          </div>
          
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Original Content</th>
                  <th>Cleaned Content</th>
                </tr>
              </thead>
              <tbody>
                {filteredContents.map((line, index) => (
                  <tr key={index}>
                    <td className="line-content original">{line}</td>
                    <td className="line-content cleaned">{cleanLineContent(line)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default App; 