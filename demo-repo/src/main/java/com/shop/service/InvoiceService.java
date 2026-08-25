package com.shop.service;

import com.shop.model.Customer;

public class InvoiceService {

    public String generateInvoice(Customer customer, double amount) {
        // Assumes email is ALWAYS present. Calls .toUpperCase() directly on it.
        String recipient = customer.getEmail().toUpperCase();
        return "Invoice for " + recipient + " : $" + amount;
    }
}
