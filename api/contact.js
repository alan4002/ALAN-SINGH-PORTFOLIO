const nodemailer = require('nodemailer');

module.exports = async (req, res) => {
  // Only accept form submissions (POST)
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Read what the visitor typed
  const { name, email, message } = req.body || {};
  if (!name || !email || !message) {
    return res.status(400).json({ error: 'All fields are required' });
  }

  // Connect to Gmail using the secret values you will set in Vercel
  const transporter = nodemailer.createTransport({
    service: 'gmail',
    auth: {
      user: process.env.GMAIL_USER,
      pass: process.env.GMAIL_APP_PASSWORD
    }
  });

  try {
    // Send the email to yourself
    await transporter.sendMail({
      from: process.env.GMAIL_USER,
      to: process.env.GMAIL_USER,
      replyTo: email,
      subject: 'Portfolio message from ' + name,
      text: message + '\n\nFrom: ' + name + ' <' + email + '>'
    });
    res.status(200).json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: 'Could not send message' });
  }
};
