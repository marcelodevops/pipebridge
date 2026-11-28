pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'mkdir -p dist && echo "binary-payload" > dist/app.bin'
                stash name: 'dist-bin', includes: 'dist/**', excludes: 'dist/*.tmp'
            }
        }
        stage('Verify') {
            parallel {
                stage('Unit Tests') {
                    environment {
                        TEST_TYPE = 'unit'
                    }
                    steps {
                        unstash 'dist-bin'
                        sh 'test -f dist/app.bin && echo "${TEST_TYPE} tests succeeded"'
                    }
                }
                stage('Lint') {
                    environment {
                        TEST_TYPE = 'lint'
                    }
                    steps {
                        sh 'echo "${TEST_TYPE} checks succeeded"'
                    }
                }
            }
        }
        stage('Package') {
            steps {
                unstash 'dist-bin'
                sh 'tar -czf dist/app.tar.gz dist/app.bin'
            }
        }
    }
}
