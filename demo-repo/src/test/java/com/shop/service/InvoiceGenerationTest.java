package com.shop.service;

import com.shop.model.Customer;

public class InvoiceGenerationTest {

    public void testGenerateInvoice() {
        Customer customer = new Customer();
        customer.setEmail("test@example.com");
        InvoiceService service = new InvoiceService();
        String result = service.generateInvoice(customer, 100.0);
        assert result != null;
    }
}
