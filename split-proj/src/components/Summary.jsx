import React, { useState } from 'react';
import './Summary.css';

const PAYMENT_MODELS = [
  'All',
  'Bayad Center',
  'Bancnet',
  'BDO',
  'ECPay',
  'SM',
  'Eprime',
  'LBC',
  'Metrobank',
  'Cebuana',
  'PrimeTap',
  'AllEasy',
  'PNB',
  'UnionBank',
  'BDO-New',
  'Unknown'
];

const formatAmount = (amount) => {
  try {
    if (!amount) return '₱0.00';
    const numAmount = typeof amount === 'string' ? parseFloat(amount.replace(/[₱,]/g, '')) : amount;
    return new Intl.NumberFormat('en-PH', {
      style: 'currency',
      currency: 'PHP',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(numAmount);
  } catch (e) {
    console.error('Error formatting amount:', e);
    return '₱0.00';
  }
};

const SummaryCard = ({ title, data, renderItem }) => {
  const safeData = data || {};
  
  const sortedData = Object.entries(safeData)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);

  return (
    <div className="summary-card">
      <h3>{title}</h3>
      <div className="summary-list">
        {sortedData.map(([key, value]) => (
          <div key={key} className="summary-item">
            {renderItem(key, value)}
          </div>
        ))}
      </div>
    </div>
  );
};

const PaymentSummaryTable = ({ entries }) => {
  const [selectedModel, setSelectedModel] = useState('All');

  const paymentTotals = React.useMemo(() => {
    if (!entries || !Array.isArray(entries)) return { items: [], grandTotal: 0 };
    
    const totals = {};
    let grandTotal = 0;
    
    // Filter entries based on selected payment model
    const filteredEntries = selectedModel === 'All' 
      ? entries 
      : entries.filter(entry => entry.paymentType === selectedModel);
    
    // Calculate totals
    filteredEntries.forEach(entry => {
      const type = entry.paymentType || 'Unknown';
      const amount = parseFloat(entry.amount?.toString().replace(/[₱,]/g, '')) || 0;
      
      if (!totals[type]) {
        totals[type] = { count: 0, amount: 0 };
      }
      
      totals[type].count += 1;
      totals[type].amount += amount;
      grandTotal += amount;
    });
    
    // Convert to array and sort by amount
    const sortedTotals = Object.entries(totals)
      .map(([type, value]) => ({
        type,
        ...value,
        percentage: (value.amount / grandTotal) * 100
      }))
      .sort((a, b) => b.amount - a.amount);
    
    return { items: sortedTotals, grandTotal };
  }, [entries, selectedModel]);

  return (
    <div className="summary-card payment-summary-card">
      <div className="payment-summary-header">
        <h3>Payment Summary</h3>
        <select 
          value={selectedModel} 
          onChange={(e) => setSelectedModel(e.target.value)}
          className="payment-model-select"
        >
          {PAYMENT_MODELS.map(model => (
            <option key={model} value={model}>{model}</option>
          ))}
        </select>
      </div>
      <div className="payment-summary-table-wrapper">
        <table className="payment-summary-table">
          <thead>
            <tr>
              <th>Payment Type</th>
              <th>Count</th>
              <th>Total Amount</th>
              <th>Percentage</th>
            </tr>
          </thead>
          <tbody>
            {paymentTotals.items.map(({ type, count, amount, percentage }) => (
              <tr key={type}>
                <td>
                  <span className={`payment-badge ${type.toLowerCase().replace(/[^a-z0-9]/g, '-')}`}>
                    {type}
                  </span>
                </td>
                <td>{count}</td>
                <td className="amount">{formatAmount(amount)}</td>
                <td>{percentage.toFixed(2)}%</td>
              </tr>
            ))}
            <tr className="grand-total">
              <td>Total</td>
              <td>{paymentTotals.items.reduce((sum, item) => sum + item.count, 0)}</td>
              <td className="amount">{formatAmount(paymentTotals.grandTotal)}</td>
              <td>100%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};

const Summary = ({ data }) => {
  if (!data || !data.summary) {
    console.log('No data available for Summary component');
    return null;
  }

  const { summary, entries } = data;
  console.log('Summary data:', summary);

  return (
    <div className="summary-section">
      <h2>Summary</h2>
      <div className="summary-grid">
        <PaymentSummaryTable entries={entries} />
        <SummaryCard
          title="Prefix Distribution"
          data={summary.prefixCount}
          renderItem={(key, value) => (
            <>
              <span className="prefix-badge">{key}</span>
              <span className="count-badge">{value}</span>
            </>
          )}
        />
        <SummaryCard
          title="Area Distribution"
          data={summary.areaCount}
          renderItem={(key, value) => (
            <>
              <span className="area-name">{key}</span>
              <span className="count-badge">{value}</span>
            </>
          )}
        />
        <div className="summary-card processing-summary">
          <h3>Processing Summary</h3>
          <div className="summary-list">
            <div className="summary-item">
              <span className="summary-label">Total Lines:</span>
              <span className="count-badge">{summary.totalLines || 0}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Processed Lines:</span>
              <span className="count-badge">{summary.processedLines || 0}</span>
            </div>
            {summary.unknownPaymentTypes && summary.unknownPaymentTypes.length > 0 && (
              <div className="summary-item unknown-types">
                <span className="summary-label">Unknown Payment Types:</span>
                <div className="unknown-types-list">
                  {summary.unknownPaymentTypes.map((type, index) => (
                    <span key={index} className="unknown-type-badge">{type}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Summary; 