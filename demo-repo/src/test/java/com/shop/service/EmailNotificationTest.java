package com.shop.service;

import com.shop.model.Customer;

public class EmailNotificationTest {

    public void testSendWelcome() {
        Customer customer = new Customer();
        customer.setEmail("welcome@example.com");
        NotificationService service = new NotificationService();
        service.sendWelcome(customer);
    }
}
