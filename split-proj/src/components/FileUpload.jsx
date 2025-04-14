import React, { useCallback } from 'react';
import './FileUpload.css';

const FileUpload = ({ onFileUpload, isLoading }) => {
  const validateFile = (file) => {
    // Check if file exists
    if (!file) {
      throw new Error('No file selected');
    }

    // Check file type
    const validTypes = ['.txt', '.csv', 'text/plain', 'text/csv'];
    const fileType = file.type || file.name.substring(file.name.lastIndexOf('.'));
    if (!validTypes.some(type => fileType.toLowerCase().includes(type.toLowerCase()))) {
      throw new Error('Please upload a .txt or .csv file');
    }

    // Check file size (max 10MB)
    const maxSize = 10 * 1024 * 1024; // 10MB in bytes
    if (file.size > maxSize) {
      throw new Error('File size must be less than 10MB');
    }

    return true;
  };

  const handleFileChange = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    
    try {
      const file = event.target.files[0];
      if (validateFile(file)) {
        console.log('File selected:', file.name, 'Type:', file.type, 'Size:', file.size);
        onFileUpload(file);
      }
    } catch (error) {
      console.error('File validation error:', error);
      alert(error.message);
    } finally {
      // Reset the input value to allow selecting the same file again
      event.target.value = '';
    }
  }, [onFileUpload]);

  const handleDragOver = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  const handleDrop = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    
    try {
      const file = event.dataTransfer.files[0];
      if (validateFile(file)) {
        console.log('File dropped:', file.name, 'Type:', file.type, 'Size:', file.size);
        onFileUpload(file);
      }
    } catch (error) {
      console.error('File validation error:', error);
      alert(error.message);
    }
  }, [onFileUpload]);

  return (
    <div className="file-upload-container">
      <div 
        className={`upload-box ${isLoading ? 'loading' : ''}`}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <div className="upload-icon">
          <i className="fas fa-cloud-upload-alt"></i>
        </div>
        <h3>Upload Your Text File</h3>
        <p>Drag and drop your file here or click to browse</p>
        <p className="file-types">Accepted file types: .txt, .csv</p>
        <div className="upload-button-container">
          <label className="upload-button">
            Choose File
            <input
              type="file"
              accept=".txt,.csv"
              onChange={handleFileChange}
              disabled={isLoading}
              style={{ display: 'none' }}
            />
          </label>
        </div>
        {isLoading && (
          <div className="loading-spinner">
            <div className="spinner"></div>
            <p>Processing your file...</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default FileUpload; 